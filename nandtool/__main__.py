import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from nandtool.config import get_configs
from nandtool.mount import mount
from nandtool.logger import setup_logging

LOGGER = logging.getLogger("nandtool")


if __name__ == "__main__":

    parser = ArgumentParser(description="The parent parser", add_help=False)

    main_parser = ArgumentParser(prog="mode")
    subparsers = main_parser.add_subparsers(title="mount or list", required=True, dest="type")

    parser_mount = subparsers.add_parser("mount", parents=[parser], help="mount (ecc corrected) partitions of the image")
    parser_mount.add_argument("image", type=Path, help="path to image")
    parser_mount.add_argument("-m", "--mount_point", type=Path, help="path to mount point", required=True)
    parser_mount.add_argument("-c", "--config", help="path or key of configuration file", required=True)

    parser_list = subparsers.add_parser("list", parents=[parser], help="list available config files")

    args = main_parser.parse_args()


    
    config_files = get_configs()

    if args.type == "list":
        print("Available configurations:")
        for file in sorted(config_files):
            print(f"  {file}")
        sys.exit(0)

    setup_logging(LOGGER)

    if args.type == "mount":
        if args.config in config_files:
            args.config = Path(config_files[args.config])
        else:
            args.config = Path(args.config)

        sys.exit(mount(args.image, args.mount_point, args.config))
