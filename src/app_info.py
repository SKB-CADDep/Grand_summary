"""Имя, версия и локальные пути приложения."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "GrandSummary"
# Первая передача в работу. Номер меняется только по явной просьбе.
APP_VERSION = "0.0.1"
LAUNCHER_EXE_NAME = "GrandSummary.exe"
APP_EXE_NAME = "GrandSummary.exe"
DATA_DIR_ENV = "GRAND_SUMMARY_DATA_DIR"
USER_PREFERENCES_ENV = "GRAND_SUMMARY_USER_PREFERENCES"
UPDATES_DIR_ENV = "GRAND_SUMMARY_UPDATES_DIR"
FORCE_UPDATE_ENV = "GRAND_SUMMARY_FORCE_UPDATE"
# Общая папка релизов. Рядом лежат GrandSummary.exe, manifest.json и releases/<версия>/.
SHARED_UPDATES_DIR = Path(
    r"\\Fileserver\утз\10 Служба технического директора\05 СКБт\!Общая\grand_summary"
)


def local_app_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"
