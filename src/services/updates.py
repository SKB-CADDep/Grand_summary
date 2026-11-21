from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from src.app_info import APP_NAME, APP_VERSION, UPDATES_DIR_ENV


def write_manifest(dist_dir: Path, version: str) -> Path:
    path = Path(dist_dir) / "manifest.json"
    path.write_text(
        json.dumps({"name": APP_NAME, "version": version}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _read_version(manifest: Path) -> str | None:
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = str((data or {}).get("version") or "").strip()
    return version or None


def _updates_dir() -> Path | None:
    configured = str(os.environ.get(UPDATES_DIR_ENV) or "").strip()
    if not configured:
        return None
    path = Path(configured)
    return path if path.is_dir() else None


def status() -> dict:
    frozen = bool(getattr(sys, "frozen", False))
    source = _updates_dir()
    latest = _read_version(source / "manifest.json") if source else None
    available = bool(latest and latest != APP_VERSION)
    if not frozen:
        return {
            "supported": False,
            "enabled": False,
            "current_version": APP_VERSION,
            "latest_version": latest,
            "update_available": available,
            "message": None,
        }
    if source is None:
        return {
            "supported": True,
            "enabled": False,
            "current_version": APP_VERSION,
            "latest_version": None,
            "update_available": False,
            "message": "Источник обновлений не настроен.",
        }
    return {
        "supported": True,
        "enabled": True,
        "current_version": APP_VERSION,
        "latest_version": latest,
        "update_available": available,
        "message": None,
    }


def apply_update() -> dict:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Обновление доступно только в собранном приложении.")
    source = _updates_dir()
    latest = _read_version(source / "manifest.json") if source else None
    if source is None or not latest:
        raise RuntimeError("Источник обновлений не настроен.")
    bundle = source / "releases" / latest / APP_NAME
    if not bundle.is_dir():
        raise RuntimeError(f"Нет пакета версии {latest}.")
    target = Path(sys.executable).resolve().parent
    shutil.copytree(bundle, target, dirs_exist_ok=True)
    from desktop.run import request_shutdown

    request_shutdown()
    return {"started": True, "version": latest}
