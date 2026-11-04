from __future__ import annotations

import shutil
import sys
from pathlib import Path


def bundle_root() -> Path:
    """Каталог ресурсов: исходники или распаковка PyInstaller."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """Каталог записи: рядом с .exe или корень репозитория."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def frontend_dist() -> Path:
    return bundle_root() / "frontend" / "dist"


def templates_dir() -> Path:
    return bundle_root() / "templates"


def docs_dir() -> Path:
    return bundle_root() / "docs"


def _seed_from_bundle(name: str) -> None:
    dest_dir = project_root() / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.is_file():
        return
    src = bundle_root() / "data" / name
    if src.is_file() and src.resolve() != dest.resolve():
        shutil.copy2(src, dest)


def data_dir() -> Path:
    path = project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    _seed_from_bundle("objects.json")
    _seed_from_bundle("acl.json")
    return path


def catalog_path() -> Path:
    return templates_dir() / "parameter_catalog.json"


def triangle_mapping_path() -> Path:
    return templates_dir() / "triangle_mapping.json"


def objects_seed_path() -> Path:
    return data_dir() / "objects.json"


def db_path() -> Path:
    return data_dir() / "grand_summary.db"


def acl_path() -> Path:
    return data_dir() / "acl.json"


def rules_path() -> Path:
    return templates_dir() / "rules.json"
