"""Имя, версия и локальные пути приложения."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "GrandSummary"
APP_VERSION = "1.0.0"
LAUNCHER_EXE_NAME = "GrandSummary.exe"
DATA_DIR_ENV = "GRAND_SUMMARY_DATA_DIR"
USER_PREFERENCES_ENV = "GRAND_SUMMARY_USER_PREFERENCES"
UPDATES_DIR_ENV = "GRAND_SUMMARY_UPDATES_DIR"


def local_app_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"
