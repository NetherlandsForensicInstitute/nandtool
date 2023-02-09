import mmap
import bchlib
import logging
import numpy as np
from itertools import chain
from tqdm import tqdm
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def modify_buffer(buffer, reverse=False, invert=False):
    array = np.frombuffer(buffer, "u1")
    if invert:
        array = array ^ 0xFF
    if reverse:
        array = ((array * 0x0202020202) & 0x010884422010) % 1023  # C trickery to bitwise reverse a byte
    return array.astype("u1").tobytes()


def build_partitions(image, conf):
    partitions = dict()
    for partition in conf.partitions:
        partconf = conf[partition]
        LOGGER.info(f"Start building partition: {partition}")
        partitions[partition] = NAND(image, partconf)
        LOGGER.info(f"Done building partition: {partition}")
    return partitions


class NAND:
    def __init__(self, path, conf):
        self.path = path
        self.f = open(self.path, "rb")
        conf = conf.to_dict()  # If we keep using the dynaconf object throughout the code, access will be slow
        self.conf = conf
        layout = conf["layout"]
        if conf["endblock"] == -1:
            conf["endblock"] = Path(path).stat().st_size // layout["blocksize"] - 1
        num_blocks = conf["endblock"] + 1 - conf["startblock"]
        self.size_with_oob = num_blocks * layout["blocksize"]
        self.mm = mmap.mmap(
            self.f.fileno(), length=self.size_with_oob, offset=conf["startblock"] * layout["blocksize"], access=mmap.ACCESS_READ
        )
        self.pagesize = layout["pagesize"]
        self.oobsize = layout["oobsize"]

        if layout["ecc_algorithm"]:
            self.bch = bchlib.BCH(layout["ecc_algorithm"]["poly"], layout["ecc_algorithm"]["t"])
        else: 
            self.bch = None
        # Avoid diving into dynaconf for every single chunk correction, which is slow!
        self.ecc = layout["ecc"]
        self.ecc_protected_data = layout["ecc_protected_data"]

        self.user_data = layout["user_data"]
        self.left_shift = layout["left_shift_ecc_buf"]
        
        self.ecc_protected_data_reverse = layout["ecc_protected_data_reverse"]
        self.ecc_protected_data_invert = layout["ecc_protected_data_invert"]
        self.ecc_reverse = layout["ecc_reverse"]
        self.ecc_invert = layout["ecc_invert"]

        if hasattr(layout, "etfs") or 'etfs' in layout:
            self.etfs_layout = layout["etfs"]
        else:
            self.etfs_layout = dict()

        pagesize = sum((end - start for chunk in self.user_data for start, end in chunk))
        if self.etfs_layout:
            pagesize += 16
        # pagesize = layout["pagesize"] if not self.etfs_layout else layout["pagesize"] + 16
        self.corrected_partition_size = num_blocks * layout["pages_per_block"] * pagesize

        # This actually starts the ECC correction
        self.corrected_bits = 0
        self.corrected = self.correct_partition()
        LOGGER.info(f"Corrected {self.corrected_bits} bits")

    def __del__(self):
        self.mm.close()
        self.f.close()

    @staticmethod
    def rebuild_buffer(mapping, raw_pagesize=None):
        if not raw_pagesize:
            raise ValueError("Invalid arguments, need raw_pagesize!")
        out = b""
        cursor = 0
        for offset, buf in sorted(mapping.items(), key=lambda x: x[0]):
            if offset > cursor:
                out += b"\xff" * (offset - cursor)
                cursor += offset - cursor
            out += buf
            cursor += len(buf)
        if len(out) < raw_pagesize:
            out += b"\xff" * (raw_pagesize - len(out))
        return out

    def bch_correct_chunk(self, data_ranges, ecc_ranges, data_map):
        data = b"".join(data_map[start] for start, _ in data_ranges)
        ecc = b"".join(data_map[start] for start, _ in ecc_ranges)
        data = modify_buffer(data, invert=self.ecc_protected_data_invert, reverse=self.ecc_protected_data_reverse)
        ecc = modify_buffer(ecc, invert=self.ecc_invert, reverse=self.ecc_reverse)
        leftshift = self.left_shift
        if leftshift == 4:
            ecc = bytes.fromhex(ecc.hex()[1:] + "0")
        flips, data_corrected, ecc_corrected = self.bch.decode(data, ecc)
        if leftshift == 4:
            ecc_corrected = bytes.fromhex("0" + ecc_corrected.hex()[:-1])
        data_corrected = modify_buffer(data_corrected, invert=self.ecc_protected_data_invert, reverse=self.ecc_protected_data_reverse)
        ecc_corrected = modify_buffer(ecc_corrected, invert=self.ecc_invert, reverse=self.ecc_reverse)
        if flips == -1:
            raise ValueError("Uncorrectable number of bitflips.")
        if flips:
            self.corrected_bits += flips
            LOGGER.debug(f"Detected {flips} flips")

        for start, end in data_ranges:
            length = end - start
            data_map[start] = data_corrected[:length]
            data_corrected = data_corrected[length:]
        assert not data_corrected
        for start, end in ecc_ranges:
            length = end - start
            data_map[start] = ecc_corrected[:length]
            ecc_corrected = ecc_corrected[length:]
        assert not ecc_corrected

    def correct_page(self, page):
        # Do correction
        data_map = dict()
        all_erased = True
        for chunk in chain(self.ecc_protected_data, self.ecc):
            for start, end in chunk:
                buf = page[start:end]
                if buf != b"\xff" * len(buf):
                    all_erased = False
                data_map[start] = buf
        if not all_erased:
            for chunk_data_ranges, chunk_ecc_ranges in zip(self.ecc_protected_data, self.ecc):
                self.bch_correct_chunk(chunk_data_ranges, chunk_ecc_ranges, data_map)  # update data_map with corrected data
        # Rebuild page data
        corrected_page = self.rebuild_buffer(data_map, raw_pagesize=self.pagesize + self.oobsize)
        return corrected_page

    def correct_partition(self):
        out = []
        raw_pagesize = self.pagesize + self.oobsize

        for i in tqdm(range(0, self.size_with_oob, raw_pagesize)):
            page = self.mm[i : i + raw_pagesize]
            if self.ecc and self.ecc_protected_data and self.bch:
                corrected_page = self.correct_page(page)
            else:
                corrected_page = page
            userdata = b""
            for chunk in self.user_data:
                for start, end in chunk:
                    userdata += corrected_page[start:end]
            # Append transaction in case of ETFS
            if self.etfs_layout:
                userdata += self.build_transaction(corrected_page)
            out.append(userdata)
        return b"".join(out)

    def build_transaction(self, page):
        transaction = b""
        start, end = self.etfs_layout["fid"]
        transaction += page[start:end]
        transaction += b"\x00" * 2  # fid padding?
        for key in ("cluster", "nclusters"):
            start, end = self.etfs_layout[key]
            transaction += page[start:end]
        transaction += b"\x00" * 2  # tacode and dacode
        start, end = self.etfs_layout["sequence"]
        transaction += page[start:end]
        return transaction
