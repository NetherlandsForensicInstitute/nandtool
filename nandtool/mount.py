import logging
import mmap
import os
import stat
from pathlib import Path
from time import time

from fuse import FUSE, Operations

from nandtool.config import load_config
from nandtool.nand import build_partitions

LOGGER = logging.getLogger(__name__)


class FuseNAND(Operations):
    """Fuse implementation of the ETFS file system.

    Args:
        image (Path): Path to the image.
        offset (int): Start of the ETFS partition in the image.
    """

    def __init__(self, image_path, mountpoint, conf):
        self.mountpoint = Path(mountpoint)

        self.image_path = image_path
        self.f = open(self.image_path, "rb")
        self.mm = mmap.mmap(
            self.f.fileno(),
            0,
            access=mmap.ACCESS_READ,
        )

        self.partitions = build_partitions(self.mm, conf)
        LOGGER.info(f"NAND chip is now mounted at {mountpoint}")

    def close(self):
        self.mm.close()
        self.f.close()

    def getattr(self, path, fh=None):
        """Get directory with stat information.

        Args:
            path (Path): Path.
            fh: file handle.

        Returns:
            dict: dictionary with keys identical to the stat C structure of stat(2).
        """
        LOGGER.debug(f"getattr({path})")
        path = Path(path)
        st = os.lstat(self.mountpoint.parent)
        if path == Path("/"):
            return dict(
                (key, getattr(st, key))
                for key in ("st_atime", "st_ctime", "st_gid", "st_mode", "st_mtime", "st_nlink", "st_size", "st_uid")
            )
        elif path.name in self.partitions:
            part = self.partitions[path.name]
            return {
                "st_mode": 0o444 | stat.S_IFREG,
                "st_nlink": 2,
                "st_size": part.corrected_partition_size,
                "st_atime": time(),
                "st_ctime": time(),
                "st_mtime": time(),
                "st_gid": 0,
                "st_uid": 0,
            }
        return dict()

    def readdir(self, path, fh):
        """Read content from directory.

        Args:
            path (Path): Path to directory.
            fh: file handle.

        Returns:
            dict: dictionary with keys identical to the stat C structure of stat(2).
        """
        LOGGER.debug(f"readdir({path})")
        path = Path(path)
        if path == Path("/"):
            for part in self.partitions:
                yield part

    def read(self, path, size, offset, fh):
        """Read content from an object.

        Args:
            path (Path): Path to object.
            size (int): size of content to be read.
            offset (int): starting offset in the file.
            fh: file handle.

        Returns:
            bytes: Raw file content.
        """
        LOGGER.debug(f"read({path}, {size}, {offset})")
        path = Path(path)
        if path.parent == Path("/") and path.name in self.partitions:
            partition = self.partitions[path.name]
            return partition.corrected[offset : offset + size]
        return b""


def mount(image, mount_point, conf):
    if not image.exists():
        LOGGER.warning(f"Image file {image} not found, exiting.")
        return -1

    if not mount_point.exists():
        LOGGER.warning(f"Mount point {mount_point} not found, exiting.")
        return -2

    if not conf.exists():
        LOGGER.warning(f"Configuration file {conf} not found, exiting.")
        return -3

    LOGGER.info(f"Mounting corrected image {image} on mount point {mount_point} with configuration {conf}")
    conf = load_config(conf)
    nand = FuseNAND(image, mount_point, conf)
    call_fuse(nand, mount_point)
    nand.close()
    LOGGER.info(f"Unmounting image {image} from mount point {mount_point}")


def call_fuse(nand, mount_point):
    FUSE(nand, str(mount_point), nothreads=True, foreground=True)
