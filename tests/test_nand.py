import os
from pathlib import Path

import bchlib
import pytest

from nandtool.config import load_config
from nandtool.nand import NAND, Layout, build_partitions, modify_buffer


@pytest.fixture
def test_image_data():
    path = Path(__file__).parent / "data/test_image.bin"
    if not path.exists():
        create_test_image()

    with open(path, "rb") as f:
        return f.read()


def example_config():
    return load_config(Path(__file__).parent / "../nandtool/configs/example.toml")


def encode(data, config):
    data = modify_buffer(data, config.data_invert, config.ecc_reverse)
    return data


def decode(ecc, config):
    if config.left_shift == 4:
        ecc = bytes.fromhex("0" + ecc.hex()[:-1])
    ecc = modify_buffer(ecc, config.ecc_invert, config.ecc_reverse)
    return ecc


def create_page(config):
    raw_page_size = config.pagesize + config.oobsize
    start_data = bytearray(os.urandom(raw_page_size))

    for chunk_data_ranges, chunk_ecc_ranges in zip(config.protected_data, config.ecc):
        chunk_data = b"".join(start_data[start:end] for start, end in chunk_data_ranges)

        enc_data = encode(chunk_data, config)
        enc_ecc = config.bch.encode(enc_data)
        chunk_ecc = decode(enc_ecc, config)

        for start, end in chunk_ecc_ranges:
            assert (
                len(chunk_ecc) == end - start
            ), f"length of ecc {len(chunk_ecc)} not equal to expected {end} - {start}"
            start_data = start_data[:start] + chunk_ecc + start_data[end:]

    return start_data


def create_test_image():
    config = example_config()

    partition_data = {}
    for partition in config.partitions:
        if partition == "RAW":
            continue

        startblock = config[partition].startblock
        endblock = config[partition].endblock
        layout = Layout(config[partition].layout)
        num_pages = layout.pages_per_block

        n = (endblock - startblock + 1) * num_pages
        partition_data[(startblock, endblock)] = b"".join(
            [create_page(layout)[0] for _ in range(n)]
        )

    with open(Path(__file__).parent / "data/test_image.bin", "wb") as f:
        partition_data = sorted(partition_data.items())
        for i, ((start, end), data) in enumerate(partition_data):
            _, previous_end = partition_data[i - 1][0]
            if start - previous_end - 1 > 0:
                block_len = len(data) // (end - start + 1)
                n = start - previous_end - 1
                f.write(bytearray(os.urandom(n * block_len)))
            f.write(data)


def test_modify_buffer():
    data = b"\xde\x3d\x54\xd9\x9b\xfa\xd6\x65\x3b\xff"

    assert modify_buffer(data) == data
    assert (
        modify_buffer(data, invert=True) == b"\x21\xc2\xab\x26\x64\x05\x29\x9a\xc4\x00"
    )
    assert (
        modify_buffer(data, reverse=True) == b"\x7b\xbc\x2a\x9b\xd9\x5f\x6b\xa6\xdc\xff"
    )
    assert (
        modify_buffer(data, reverse=True, invert=True)
        == b"\x84\x43\xd5\x64\x26\xa0\x94\x59\x23\x00"
    )
    assert modify_buffer(None) == None


def test_correct_chunk():
    config = example_config()
    nand = NAND(test_image_data, config["SIMPLE"])

    data = b"\xe9\xbdD\x03aJ\xd1\x1bK\xee\xa0\xd7\x9e\x0b\x11\xb1\x8d+x\xe1\x0bB\xad\x96\x88\xbe'*\x8a\x13,\xe3y\xa3[?\xec\xd5\xc7{f\x16\xe4\xd7G\xe5\x02\x98\x1c\xa6\xec\xfcD_\x17\xeb\xc8\x82&\t\xf0\x9a\xf8\x98\xeb\xf3\x98;\xa5\x99\xcc\x83\x0cz\xef+\xce\xe0\xed\x83@{\xe2\xfd\x91\xf7\xeb\xdc\xd7D\x7fC\xc6\xcdxj\x03\x00\xc3\r\xce\xc6RO\x8e\x82\xbf\xdc{\xc6\xf4\x97\x01A.\x9f\xd9\xe9\xda\x82\xe6Q\xf2\x8c8\xedOt\x8a\xb2=o0]q\\\xc4\xbe\xe0\x08\x8c\x98X`\x1f\xfd$&\xd4\x10#\x08\xcc\xc9\xb3\xd1q\xff\x04\xd8\xdb(\"X\x9ebYl\xde\xfb8\x97\xdc\xe6\xd9\xb7\xeb\x96\x0f\x08`\x08e\x08\xbd\xef\x8a\xe6\xed\xdd \xe7\xd9\xac\\-\xad\xbb\xaa\xc8@\x1f\xc7D\xa1\xb3\xb5/\n\xa0\xca\xa7J\xd3\xacK$\x13\x15!\xd0\xc6\xf8\xd8>\xbc\x04)p\x16\xdb\xe9\xff1\xfap\r\x13\xf2\x9e\xc5Q]\x16\x06\xe4\x8e\xe1\xcbE\xcb\xee\x96\xc1%@\xb0#\xb5\x8ad)6_4\x9c\x8cu,<<\xc99\x02\x88\x02\x828\x92\x03\xe9\xca\xf1\xf2\xddf\xe4\xbf`\xc6RsCv\xa8\xd3`h\x04\xa6|\x01\xa1\xed\xe6\xa9\xaf\xe6\xc9\x00\\|g~s\xbb\xba\xb9\xbc'\xb1}UTS\x86d\xd6\xf3jJ_\xc7\x16\xe6\x930\xd6\x1a.!P]\xcc\xaa\x1c\xd3}\n\x7fd\xc9\xa1\xa6\x91\xe9D'\xfb?\xe7\xde\x83\xedr_nt\x01\xea\x99Y\x0f9=\xcd.\x1bz\xd2\xd9e\xc9u\t\x0e#)O\xd9\xc0\xd2\xe8\x93<d\xdc\xbd1\xea\xd6\x97\\X\x1d\xf8L\x1d\xda\x83\x08\xdd\xbdSb\x8a62\xce\x9f\xe5]H\xfc\xec\xcc\xf2\x83\xdd\xa4\xc6\xcb\xd7-\xe4\x9ds\xb9\xe9\xa1\xff4\xd4\x97\xda\x82L\xa8d\xd9S\xd3g\xa4\x9eM\x95\xd7\x16>\xcf\xfc\xf6\n\x84(M\x8b\r\xee'\x8d\x94\xcau\x9b\xa1\xe3*\xe0\x91A\xac\xc6E\x05\xe29\x10j5\n\xfb\x076\xf4\xf92\xcb\xccW\x17\xadf^[\xe5\x19T\xc6u\xd5"
    ecc = b'\xbd"\x82\xbe\x185\xa0'

    nand.bch_correct_chunk(data, ecc)
    assert (
        nand.corrected_bits == 0
    ), "Bitflip(s) incorrectly detected when ecc correcting chunk"

    data_flip = (int.from_bytes(data, "big") ^ 0x0100).to_bytes(len(data), "big")
    data, ecc, uncorrectable = nand.bch_correct_chunk(data_flip, ecc)
    assert (
        nand.corrected_bits == 1
    ), f"Incorrect number of bitflips detected ({nand.corrected_bits}), should be 1"
    assert not uncorrectable, "Invalid detection of correctable flips"

    data, ecc, uncorrectable = nand.bch_correct_chunk(data, b"\x00" * 7)
    assert uncorrectable, "Invalid detection of uncorrectable errors"


def test_image(test_image_data):
    config = example_config()
    build_partitions(test_image_data, config)
