from __future__ import annotations

import sys

from src.app_info import APP_VERSION
from src.services.release_sync import (
    check_for_update,
    dist_root,
    launch_launcher_for_update,
    published_version,
    version_key,
    write_manifest,
)

__all__ = ["write_manifest", "status", "apply_update"]


def status() -> dict:
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return {
            "supported": False,
            "enabled": False,
            "current_version": APP_VERSION,
            "latest_version": None,
            "update_available": False,
            "message": None,
        }
    source = dist_root()
    if source is None or not source.is_dir():
        return {
            "supported": True,
            "enabled": False,
            "current_version": APP_VERSION,
            "latest_version": None,
            "update_available": False,
            "message": "Источник обновлений не настроен.",
        }
    latest = published_version(source)
    available = bool(latest and version_key(latest) > version_key(APP_VERSION))
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
    found = check_for_update()
    if found is None:
        source = dist_root()
        if source is None or not source.is_dir():
            raise RuntimeError("Источник обновлений не настроен.")
        raise RuntimeError("Установлена последняя версия.")
    try:
        launch_launcher_for_update()
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc
    from desktop.run import request_shutdown

    request_shutdown()
    return {"started": True, "version": found[1]}
