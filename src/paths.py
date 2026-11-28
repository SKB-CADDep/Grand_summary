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


def _configured_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root() / path


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


def default_working_data_dir() -> Path:
    """Рабочая база: общая папка релизов, иначе каталог рядом с exe / проектом."""
    return work_root() / "data"


def work_root() -> Path:
    """Папка текущей работы: шара релизов, каталог exe или корень проекта."""
    from src.app_info import DATA_DIR_ENV

    configured = str(os.environ.get(DATA_DIR_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().parent
    if getattr(sys, "frozen", False):
        try:
            from src.services.release_sync import dist_root

            share = dist_root()
        except Exception:
            share = None
        if share is not None and Path(share).is_dir():
            return Path(share)
    return project_root()


def data_dir() -> Path:
    from src.app_info import DATA_DIR_ENV

    configured = str(os.environ.get(DATA_DIR_ENV) or "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        path = default_working_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    _seed_from_bundle("acl.json", path)
    return path


def catalog_path() -> Path:
    return templates_dir() / "parameter_catalog.json"


def triangle_mapping_path() -> Path:
    return templates_dir() / "triangle_mapping.json"


# False — каталоги из папки текущей работы. True — пути FILESERVER_* ниже.
USE_FILESERVER_OBJECTS = False
FILESERVER_OBJECTS_DATABASE = Path(
    r"\\fileserver\УТЗ\10 Служба технического директора\05 СКБт\ОАП\1. Проекты\Grand summary\Временное бд\временно бд объектов для тестов\projects.json"
)
OBJECTS_DIR_NAME = "временно бд объектов для тестов"


def objects_database_dir() -> Path:
    configured = str(os.environ.get("GRAND_SUMMARY_OBJECTS_DIR") or "").strip()
    if configured:
        return _configured_project_path(configured)
    if USE_FILESERVER_OBJECTS:
        return FILESERVER_OBJECTS_DATABASE.parent
    return work_root() / OBJECTS_DIR_NAME


def objects_database_path() -> Path:
    configured = str(os.environ.get("GRAND_SUMMARY_OBJECTS_FILE") or "").strip()
    if configured:
        return _configured_project_path(configured)
    if USE_FILESERVER_OBJECTS:
        return FILESERVER_OBJECTS_DATABASE
    return objects_database_dir() / "projects.json"


# False — каталог из папки текущей работы. True — путь FILESERVER_MATERIALS_DIR.
USE_FILESERVER_MATERIALS = False
FILESERVER_MATERIALS_DIR = Path(
    r"\\fileserver\УТЗ\10 Служба технического директора\05 СКБт\ОАП\1. Проекты\Grand summary\Временное бд\Библиотека материалов"
)
MATERIALS_DIR_NAME = "Библиотека материалов"


def materials_database_dir() -> Path:
    configured = str(os.environ.get("GRAND_SUMMARY_MATERIALS_DIR") or "").strip()
    if configured:
        return _configured_project_path(configured)
    if USE_FILESERVER_MATERIALS:
        return FILESERVER_MATERIALS_DIR
    return work_root() / MATERIALS_DIR_NAME


def db_path() -> Path:
    return data_dir() / "grand_summary.db"


def acl_path() -> Path:
    return data_dir() / "acl.json"


def rules_path() -> Path:
    return templates_dir() / "rules.json"
