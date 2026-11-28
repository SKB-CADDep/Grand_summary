from __future__ import annotations

from typing import Literal

CombineMode = Literal["and", "or"]


def combine_compare_targets(
    ordered_ids: list[str],
    current_id: str,
    selected_ids: list[str] | None,
    range_from: str | None,
    range_to: str | None,
    combine: str = "or",
) -> list[str]:
    """Sheets to compare against: checked tabs, a contiguous range, or both together.

    Текущая вкладка из сравнения исключается. Параметр combine сохранён для API
    и больше не меняет набор вкладок.
    """
    del combine
    known = set(ordered_ids)
    picked = {sheet_id for sheet_id in (selected_ids or []) if sheet_id in known and sheet_id != current_id}
    range_set: set[str] = set()
    has_range = bool(range_from and range_to and range_from in known and range_to in known)
    if has_range:
        start = ordered_ids.index(range_from)  # type: ignore[arg-type]
        end = ordered_ids.index(range_to)  # type: ignore[arg-type]
        if start > end:
            start, end = end, start
        range_set = {sheet_id for sheet_id in ordered_ids[start : end + 1] if sheet_id != current_id}

    want = picked | range_set
    return [sheet_id for sheet_id in ordered_ids if sheet_id in want]


def values_differ(left: str | None, right: str | None) -> bool:
    return (left or "") != (right or "")
