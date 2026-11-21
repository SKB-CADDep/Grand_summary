from __future__ import annotations

from typing import Any


def cell_key(parameter_key: str, column_key: str) -> str:
    return f"{parameter_key}:{column_key}"


def snap_cells(cells: list[dict]) -> list[dict]:
    return [
        {
            "parameter_key": cell.get("parameter_key"),
            "column_key": cell.get("column_key"),
            "value": cell.get("value"),
            "draft_value": cell.get("draft_value"),
            "status": cell.get("status") or "empty",
            "hyperlink": cell.get("hyperlink"),
            "locked": bool(cell.get("locked")),
        }
        for cell in cells
    ]


def take_snap(workbook: dict | None, catalog: dict | None, extra: dict | None = None) -> dict:
    extra = extra or {}
    return {
        "cells": snap_cells((workbook or {}).get("cells") or []),
        "extra_columns": (catalog or {}).get("extra_columns") or [],
        "column_overrides": (catalog or {}).get("column_overrides") or {},
        "deleted_columns": (catalog or {}).get("deleted_columns") or [],
        "extra_parameters": (catalog or {}).get("extra_parameters") or [],
        "parameter_overrides": (catalog or {}).get("parameter_overrides") or {},
        "deleted_parameters": (catalog or {}).get("deleted_parameters") or [],
        "changeIds": extra.get("changeIds") or [],
        "changes": extra.get("changes") or [],
    }


def clear_keys(from_cells: list[dict], to_cells: list[dict]) -> list[dict]:
    keep = {cell_key(item["parameter_key"], item["column_key"]) for item in to_cells}
    return [
        item
        for item in from_cells
        if cell_key(item["parameter_key"], item["column_key"]) not in keep
    ]


def workbook_with_cell(workbook: dict, updated_cell: dict) -> dict:
    cells = list(workbook.get("cells") or [])
    index = next(
        (
            i
            for i, cell in enumerate(cells)
            if cell.get("parameter_key") == updated_cell.get("parameter_key")
            and cell.get("column_key") == updated_cell.get("column_key")
        ),
        -1,
    )
    previous = cells[index] if index >= 0 else None
    if index >= 0:
        cells[index] = updated_cell
    else:
        cells.append(updated_cell)
    unsaved = int(workbook.get("unsaved_count") or 0)
    unsaved += int(updated_cell.get("status") == "draft") - int((previous or {}).get("status") == "draft")
    next_book = dict(workbook)
    next_book["cells"] = cells
    next_book["updated_at"] = updated_cell.get("updated_at") or workbook.get("updated_at")
    next_book["unsaved_count"] = max(0, unsaved)
    return next_book


def expected_at(workbook: dict | None, parameter_key: str, column_key: str) -> str | None:
    if not workbook:
        return None
    for cell in workbook.get("cells") or []:
        if cell.get("parameter_key") == parameter_key and cell.get("column_key") == column_key:
            return cell.get("updated_at")
    return None
