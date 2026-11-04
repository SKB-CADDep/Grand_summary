from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.paths import rules_path


@lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    path = rules_path()
    if not path.is_file():
        return {"dictionaries": {}, "dictionary_for": {}, "rules": []}
    return json.loads(path.read_text(encoding="utf-8"))


def options_for(parameter_key: str) -> list[str]:
    data = load_rules()
    dict_id = (data.get("dictionary_for") or {}).get(parameter_key)
    if not dict_id:
        return []
    return list((data.get("dictionaries") or {}).get(dict_id) or [])


def matching_rules(parameter_key: str, value: str | None) -> list[dict]:
    text = (value or "").strip()
    folded = text.casefold()
    matched = []
    for rule in load_rules().get("rules") or []:
        if rule.get("trigger") != parameter_key:
            continue
        equals = rule.get("when_equals")
        if equals is not None:
            if folded == str(equals).strip().casefold():
                matched.append(rule)
            continue
        needles = [str(item).casefold() for item in rule.get("when_contains") or []]
        if needles and all(needle in folded for needle in needles):
            matched.append(rule)
    return matched


def all_lock_keys() -> set[str]:
    keys: set[str] = set()
    for rule in load_rules().get("rules") or []:
        keys.update(rule.get("lock") or [])
        for item in rule.get("copy") or []:
            keys.add(item.get("to"))
    return {key for key in keys if key}
