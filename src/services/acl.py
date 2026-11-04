from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from src.paths import acl_path


@lru_cache(maxsize=1)
def _load() -> dict:
    path = Path(os.environ.get("GRAND_SUMMARY_ACL") or acl_path())
    if not path.is_file():
        return {"editors": ["*"], "readers": []}
    return json.loads(path.read_text(encoding="utf-8"))


def reload() -> None:
    _load.cache_clear()


def _names(group: str) -> list[str]:
    values = _load().get(group) or []
    return [str(item).strip() for item in values if str(item).strip()]


def can_write(username: str) -> bool:
    editors = _names("editors")
    if not editors or "*" in editors:
        return True
    return username in editors


def can_read(username: str) -> bool:
    if can_write(username):
        return True
    readers = _names("readers")
    if "*" in readers:
        return True
    return username in readers
