from pathlib import Path

from dynaconf import Dynaconf


def get_configs():
    config_path = Path(__file__).parent / "configs"
    return {
        f.stem: f for f in config_path.iterdir() if f.is_file() and f.suffix == ".toml"
    }


def load_config(config_path: Path):
    settings = Dynaconf(
        envvar_prefix="DYNACONF",
        settings_files=[str(config_path)],
    )
    check_and_augment_conf(settings)
    return settings


def check_and_augment_conf(settings):
    # TODO: add decent checks
    for partition in settings.partitions:
        part = settings[partition]
        part.layout = settings[part.layout]
        layout = part.layout
        layout.blocksize = (layout.pagesize + layout.oobsize) * layout.pages_per_block

        if hasattr(layout, "ecc_algorithm"):
            ecc_algorithm = layout.ecc_algorithm
            layout.ecc_algorithm = (
                settings[ecc_algorithm]
                if isinstance(ecc_algorithm, str)
                else layout.ecc_algorithm
            )
        else:
            layout.ecc_algorithm = None
        if not hasattr(layout, "ecc"):
            layout.ecc = None
        if not hasattr(layout, "ecc_protected_data"):
            layout.ecc_protected_data = None

        if hasattr(layout, "etfs"):
            etfs_layout = layout.etfs
            layout.etfs = (
                settings[etfs_layout] if isinstance(etfs_layout, str) else layout.etfs
            )

        # Set default values for optional parameters
        if not hasattr(layout, "left_shift_ecc_buf"):
            layout.left_shift_ecc_buf = 0
        if not hasattr(layout, "ecc_protected_data_reverse"):
            layout.ecc_protected_data_reverse = False
        if not hasattr(layout, "ecc_protected_data_invert"):
            layout.ecc_protected_data_invert = False
        if not hasattr(layout, "ecc_reverse"):
            layout.ecc_reverse = False
        if not hasattr(layout, "ecc_invert"):
            layout.ecc_invert = False
        if not hasattr(layout, "ecc_strict"):
            layout.ecc_strict = True
