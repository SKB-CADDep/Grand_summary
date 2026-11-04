from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.paths import catalog_path, triangle_mapping_path


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        raise FileNotFoundError(f"Нет каталога параметров: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parameters() -> list[dict[str, Any]]:
    return list(load_catalog()["parameters"])


def columns() -> list[dict[str, Any]]:
    return list(load_catalog()["columns"])


def parameter_by_key(key: str) -> dict[str, Any] | None:
    for item in parameters():
        if item["key"] == key:
            return item
    return None


def column_by_key(key: str) -> dict[str, Any] | None:
    for item in columns():
        if item["key"] == key:
            return item
    return None


def editable_parameter_keys() -> list[str]:
    return [item["key"] for item in parameters() if item["row_kind"] == "editable"]


def label_to_parameter_key() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in parameters():
        mapping[item["label"].strip().casefold()] = item["key"]
        mapping[item["label_raw"].strip().casefold()] = item["key"]
    return mapping


def label_to_column_key() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in columns():
        mapping[item["label"].strip().casefold()] = item["key"]
    return mapping


@lru_cache(maxsize=1)
def load_triangle_mapping() -> dict[str, Any]:
    path = triangle_mapping_path()
    if not path.is_file():
        return {"match": "by_label", "aliases": {}}
    return json.loads(path.read_text(encoding="utf-8"))
