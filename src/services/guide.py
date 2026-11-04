from __future__ import annotations

import json
import os
from pathlib import Path

from src.paths import data_dir


def guide_seen_path() -> Path:
    override = os.environ.get("GRAND_SUMMARY_GUIDE")
    if override:
        return Path(override)
    db = os.environ.get("GRAND_SUMMARY_DB") or ""
    if db.startswith("sqlite:///"):
        return Path(db[len("sqlite:///") :]).with_name("guide_seen.json")
    if db and "://" not in db:
        return Path(db).with_name("guide_seen.json")
    return data_dir() / "guide_seen.json"


def _load() -> dict:
    path = guide_seen_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def is_guide_seen(username: str) -> bool:
    name = (username or "").strip()
    if not name:
        return False
    return bool(_load().get(name))


def mark_guide_seen(username: str) -> bool:
    name = (username or "").strip()
    if not name:
        return False
    path = guide_seen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load()
    data[name] = True
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
