import logging
from itertools import chain

import bchlib
import numpy as np
from tqdm import tqdm

LOGGER = logging.getLogger(__name__)


def modify_buffer(buffer, reverse=False, invert=False, left_shift=False):
    if not buffer:
        return None

    array = np.frombuffer(buffer, "u1")
    if invert:
        array = array ^ 0xFF
    if reverse:
        # magic calculation to bitwise reverse a byte
        array = ((array * 0x0202020202) & 0x010884422010) % 1023
    return array.astype("u1").tobytes()


def build_partitions(image_data, conf):
    partitions = dict()
    for partition in conf.partitions:
        partconf = conf[partition]
        LOGGER.info(f"Start building partition: {partition}")
        nand = NAND(image_data, partconf)
        nand.correct_partition()
        partitions[partition] = nand
        LOGGER.info(f"Done building partition: {partition}")
    return partitions


class Layout:
    """Class to avoid diving into dynaconf object for every call. Unpacking into this class speeds up code."""

    def __init__(self, layout_conf):
        # partition size info
        self.blocksize = layout_conf["blocksize"]
        self.pagesize = layout_conf["pagesize"]
        self.oobsize = layout_conf["oobsize"]
        self.pages_per_block = layout_conf["pages_per_block"]

        # layout of ecc and data in the page
        self.ecc = layout_conf["ecc"]
        self.protected_data = layout_conf["ecc_protected_data"]
        self.user_data = layout_conf["user_data"]

        # modifications to buffer
        self.left_shift = layout_conf["left_shift_ecc_buf"]
        self.data_reverse = layout_conf["ecc_protected_data_reverse"]
        self.data_invert = layout_conf["ecc_protected_data_invert"]
        self.ecc_reverse = layout_conf["ecc_reverse"]
        self.ecc_invert = layout_conf["ecc_invert"]

        self.ecc_strict = layout_conf["ecc_strict"]

        # etfs layout if specified
        if hasattr(layout_conf, "etfs") or "etfs" in layout_conf:
            self.etfs_layout = layout_conf["etfs"]
        else:
            self.etfs_layout = dict()

        # ecc algorithm if specified
        ecc_algorithm = layout_conf["ecc_algorithm"]
        if ecc_algorithm:
            self.bch = bchlib.BCH(prim_poly=ecc_algorithm["poly"], t=ecc_algorithm["t"])
        else:
            self.bch = None


class NAND:
    def __init__(self, data, part_conf):
        self.data = data

        # extract configuration of partition
        self.part_conf = part_conf.to_dict()
        self.layout = Layout(self.part_conf["layout"])
        self.start = part_conf["startblock"]
        self.end = part_conf["endblock"]
        if self.end == -1:
            self.end = len(self.data) // self.layout.blocksize - 1
        self.num_blocks = self.end + 1 - self.start
        self.raw_partition_size = self.num_blocks * self.layout.blocksize

        # calculate corrected partition size
        pagesize = sum(
            (end - start for chunk in self.layout.user_data for start, end in chunk)
        )
        if self.layout.etfs_layout:
            pagesize += 16
        self.corrected_partition_size = (
            self.num_blocks * self.layout.pages_per_block * pagesize
        )

        # start ecc correction
        self.corrected_bits = 0
        self.corrected = None

    @staticmethod
    def rebuild_buffer(mapping, raw_pagesize):
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

    def bch_correct_chunk(self, data, ecc):
        uncorrectable = False
        # modify data and ecc buffers if needed
        ecc = modify_buffer(ecc, self.layout.ecc_invert, self.layout.ecc_reverse)
        data = modify_buffer(data, self.layout.data_invert, self.layout.data_reverse)
        if self.layout.left_shift == 4:
            ecc = bytes.fromhex(ecc.hex()[1:] + "0")

        # decode chunk
        flips = self.layout.bch.decode(data, ecc)

        # check flips
        if flips == -1:
            # raise ValueError("Uncorrectable number of bitflips.")
            uncorrectable = True
        elif flips > 0:
            self.corrected_bits += flips
            LOGGER.debug(f"Detected {flips} flips")
            # correct bitflips
            data = bytearray(data)
            ecc = bytearray(ecc)
            self.layout.bch.correct(data, ecc)

        # modify data and ecc buffers to revert back
        if self.layout.left_shift == 4:
            ecc = bytes.fromhex("0" + ecc.hex()[:-1])
        ecc = modify_buffer(ecc, self.layout.ecc_invert, self.layout.ecc_reverse)
        data = modify_buffer(data, self.layout.data_invert, self.layout.data_reverse)

        return data, ecc, uncorrectable

    def correct_page(self, page):
        data_map = dict()
        all_erased = True
        uncorrectable_page = False

        # check if page is empty (all 0xff)
        for chunk in chain(self.layout.protected_data, self.layout.ecc):
            for start, end in chunk:
                buf = page[start:end]
                if buf != b"\xff" * len(buf):
                    all_erased = False
                data_map[start] = buf

        corrected_data_map = {}
        # correct if page not empty
        if not all_erased:
            for chunk_data_ranges, chunk_ecc_ranges in zip(
                self.layout.protected_data, self.layout.ecc
            ):
                # concatenate chunks
                raw_data = b"".join(data_map[start] for start, _ in chunk_data_ranges)
                raw_ecc = b"".join(data_map[start] for start, _ in chunk_ecc_ranges)

                # correct chunk
                data_corrected, ecc_corrected, uncorrectable_chunk = (
                    self.bch_correct_chunk(raw_data, raw_ecc)
                )

                uncorrectable_page |= uncorrectable_chunk

                # split corrected buffers up into chunks
                for start, end in chunk_data_ranges:
                    length = end - start
                    corrected_data_map[start] = data_corrected[:length]
                    data_corrected = data_corrected[length:]
                assert not data_corrected
                for start, end in chunk_ecc_ranges:
                    length = end - start
                    corrected_data_map[start] = ecc_corrected[:length]
                    ecc_corrected = ecc_corrected[length:]
                assert not ecc_corrected

        # Rebuild page data
        corrected_page = self.rebuild_buffer(
            corrected_data_map, self.layout.pagesize + self.layout.oobsize
        )
        return corrected_page, uncorrectable_page

    def correct_partition(self):
        corrected_pages = []
        raw_pagesize = self.layout.pagesize + self.layout.oobsize
        raw_blocksize = raw_pagesize * self.layout.pages_per_block
        start_offset = self.start * raw_blocksize

        for i in tqdm(
            range(start_offset, start_offset + self.raw_partition_size, raw_pagesize)
        ):
            # correct page if sufficient parameters available
            page = self.data[i : i + raw_pagesize]
            if self.layout.ecc and self.layout.protected_data and self.layout.bch:
                corrected_page, uncorrectable = self.correct_page(page)
                if self.layout.ecc_strict and uncorrectable:
                    raise ValueError(f"Uncorrectable bitflips in page at: 0x{i:08x}")
                elif uncorrectable:
                    print(
                        f"Uncorrectable bitflips in page at: {i:08x}, resuming with corrupt data"
                    )
            else:
                corrected_page = page

            # slice userdata from page
            userdata = b""
            for chunk in self.layout.user_data:
                for start, end in chunk:
                    userdata += corrected_page[start:end]

            # append transaction in case of ETFS
            if self.layout.etfs_layout:
                userdata += self.build_transaction(corrected_page)

            corrected_pages.append(userdata)

        self.corrected = b"".join(corrected_pages)
        LOGGER.info(f"Corrected {self.corrected_bits} bits")

    def build_transaction(self, page):
        transaction = b""
        start, end = self.layout.etfs_layout["fid"]
        transaction += page[start:end]
        transaction += b"\x00" * 2  # fid padding?
        for key in ("cluster", "nclusters"):
            start, end = self.layout.etfs_layout[key]
            transaction += page[start:end]
        transaction += b"\x00" * 2  # tacode and dacode
        start, end = self.layout.etfs_layout["sequence"]
        transaction += page[start:end]
        return transaction
