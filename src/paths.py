from __future__ import annotations

import os
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


def _seed_from_bundle(name: str, destination: Path) -> None:
    dest = destination / name
    src = bundle_root() / "data" / name
    if not dest.is_file() and src.is_file():
        shutil.copy2(src, dest)


def data_dir() -> Path:
    from src.app_info import DATA_DIR_ENV

    configured = str(os.environ.get(DATA_DIR_ENV) or "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        path = project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    _seed_from_bundle("acl.json", path)
    return path


def catalog_path() -> Path:
    return templates_dir() / "parameter_catalog.json"


def triangle_mapping_path() -> Path:
    return templates_dir() / "triangle_mapping.json"


# False — локальная папка для тестов. True — каталог на файловом сервере.
USE_FILESERVER_OBJECTS = False
FILESERVER_OBJECTS_DATABASE = Path(
    r"\\Fileserver\утз\10 Служба технического директора\05 СКБт\!Общая\objects\projects.json"
)


def objects_database_dir() -> Path:
    configured = str(os.environ.get("GRAND_SUMMARY_OBJECTS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return project_root() / "временно бд объектов для тестов"


def objects_database_path() -> Path:
    configured = str(os.environ.get("GRAND_SUMMARY_OBJECTS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    if USE_FILESERVER_OBJECTS:
        return FILESERVER_OBJECTS_DATABASE
    return objects_database_dir() / "projects.json"


def materials_database_dir() -> Path:
    configured = str(os.environ.get("GRAND_SUMMARY_MATERIALS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(r"C:\Users\nyagavrilova\Desktop\Гранд СВОДКА (Grand_summer)\БД Материалов")


def db_path() -> Path:
    return data_dir() / "grand_summary.db"


def acl_path() -> Path:
    return data_dir() / "acl.json"


def rules_path() -> Path:
    return templates_dir() / "rules.json"
