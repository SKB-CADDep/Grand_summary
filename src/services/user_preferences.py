from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.app_info import USER_PREFERENCES_ENV
from src.paths import data_dir

DEFAULTS = {
    "history_position": "right",
    "history_panel_open": True,
    "history_right_width": 360,
    "history_bottom_height": 260,
}


def preferences_path() -> Path:
    override = os.environ.get(USER_PREFERENCES_ENV)
    if override:
        return Path(override)
    return data_dir() / "user_preferences.json"


def _load() -> dict[str, Any]:
    path = preferences_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw or {}
    position = source.get("history_position")
    return {
        "history_position": position if position in {"right", "bottom"} else DEFAULTS["history_position"],
        "history_panel_open": bool(source.get("history_panel_open", DEFAULTS["history_panel_open"])),
        "history_right_width": int(source.get("history_right_width") or DEFAULTS["history_right_width"]),
        "history_bottom_height": int(source.get("history_bottom_height") or DEFAULTS["history_bottom_height"]),
    }


def get_history_preferences(username: str) -> tuple[dict[str, Any], bool]:
    name = (username or "").strip()
    stored = _load()
    if not name or name not in stored or not isinstance(stored.get(name), dict):
        return dict(DEFAULTS), False
    return _normalize(stored[name]), True


def save_history_preferences(username: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = (username or "").strip()
    preferences = _normalize(payload)
    if not name:
        return preferences
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load()
    data[name] = preferences
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return preferences
