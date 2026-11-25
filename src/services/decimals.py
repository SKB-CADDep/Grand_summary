from __future__ import annotations

import re

_DECIMAL_COMMA = re.compile(r"(?<!\d)(\d+),(\d+)")


def normalize_decimal_commas(value: str | None) -> str | None:
    """Меняет десятичную запятую на точку: 0,01 → 0.01. Текст без числа не трогает."""
    if value is None:
        return None
    return _DECIMAL_COMMA.sub(r"\1.\2", value)
