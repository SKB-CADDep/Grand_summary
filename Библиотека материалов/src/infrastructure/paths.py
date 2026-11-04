import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _THIS_FILE.parent.parent.parent


def config_dir() -> Path:
    return project_root() / "config"


def docs_dir() -> Path:
    return project_root() / "docs"


def get_app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()
