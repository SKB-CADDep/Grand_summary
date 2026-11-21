from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.models import Cell, Workbook
from src.catalog import label_to_column_key, label_to_parameter_key, load_triangle_mapping, parameters
from src.services import workbooks as workbook_service

SKIP_SHEET_TITLES = {
    "протокол изменений",
    "геом. данные",
    "проточная часть",
}
SKIP_HEADER_LABELS = {
    "",
    "ед. изм.",
    "ед.изм.",
    "единица измерения",
    "наименование параметра",
    "наименование",
    "параметр",
}
_PARENS = re.compile(r"\([^)]*\)")


def load_excel_workbook(data: bytes | BytesIO):
    return load_workbook(data, data_only=True)


def is_importable_sheet_title(title: str) -> bool:
    return title.strip().casefold() not in SKIP_SHEET_TITLES


def workbook_has_values(workbook: Workbook) -> bool:
    return any((cell.value or cell.draft_value) for cell in workbook.cells)


def copy_sheet(
    session: Session,
    source: Workbook,
    name: str,
    username: str,
    include_values: bool = True,
) -> Workbook:
    root = source.parent or source
    siblings = workbook_service.list_sheet_workbooks(session, root)
    clone = Workbook(
        id=workbook_service._new_id(),
        object_id=root.object_id,
        created_by=username,
        parent_workbook_id=root.id,
        sheet_name=(name or "Лист")[:255],
        sheet_order=len(siblings),
        is_primary=False,
        extra_columns_json=source.extra_columns_json,
        column_overrides_json=source.column_overrides_json,
        deleted_columns_json=source.deleted_columns_json,
        extra_parameters_json=source.extra_parameters_json,
        parameter_overrides_json=source.parameter_overrides_json,
        deleted_parameters_json=source.deleted_parameters_json,
    )
    session.add(clone)
    session.flush()
    if include_values:
        for cell in source.cells:
            if not (cell.value or cell.draft_value):
                continue
            session.add(
                Cell(
                    id=workbook_service._new_id(),
                    workbook_id=clone.id,
                    parameter_key=cell.parameter_key,
                    column_key=cell.column_key,
                    value=cell.value,
                    draft_value=None,
                    status="initial" if cell.value else "empty",
                    hyperlink=cell.hyperlink,
                    locked=False,
                    unified=bool(cell.unified),
                    updated_by=username,
                    updated_at=workbook_service._now(),
                )
            )
        session.flush()
    root.updated_at = workbook_service._now()
    return clone


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize_label(value: Any) -> str:
    text = _PARENS.sub(" ", _cell_text(value))
    text = text.replace(",", " ").replace(";", " ")
    return " ".join(text.casefold().split())


def _parameter_lookup() -> dict[str, str]:
    mapping: dict[str, str] = {}

    def add(label: str, key: str) -> None:
        folded = label.strip().casefold()
        normalized = _normalize_label(label)
        if folded:
            mapping[folded] = key
        if normalized:
            mapping[normalized] = key

    for item in parameters():
        key = item["key"]
        add(item.get("label") or "", key)
        add(item.get("label_raw") or "", key)
        label = item.get("label") or ""
        if "(" in label:
            add(label.split("(", 1)[0], key)
    aliases = load_triangle_mapping().get("aliases") or {}
    for alias, key in aliases.items():
        add(str(alias), str(key))
    mapping.update(label_to_parameter_key())
    return mapping


def _find_header_row(rows: list[tuple], col_by_label: dict[str, str]) -> int:
    best_index = 0
    best_score = -1
    for index, row in enumerate(rows[:25]):
        if not row:
            continue
        score = 0
        first = _cell_text(row[0]).casefold()
        if first.startswith("наименование"):
            score += 3
        for value in row[1:]:
            text = _cell_text(value)
            if col_by_label.get(text.casefold()) or col_by_label.get(_normalize_label(text)):
                score += 2
        if score > best_score:
            best_score = score
            best_index = index
    return best_index if best_score > 0 else 0


def import_sheet(session: Session, workbook: Workbook, excel_sheet, username: str) -> int:
    rows = list(excel_sheet.iter_rows(values_only=True))
    if not rows:
        return 0
    param_by_label = _parameter_lookup()
    col_by_label = label_to_column_key()
    header_index = _find_header_row(rows, col_by_label)
    header = rows[header_index]
    column_keys: dict[int, str] = {}
    for index, value in enumerate(header):
        text = _cell_text(value)
        if index == 0 or text.casefold() in SKIP_HEADER_LABELS:
            continue
        key = col_by_label.get(text.casefold()) or col_by_label.get(_normalize_label(text))
        if key:
            column_keys[index] = key
    count = 0
    allowed = workbook_service.editable_keys(workbook)
    known_columns = {item["key"] for item in workbook_service.workbook_columns(workbook)}
    for row in rows[header_index + 1 :]:
        if not row:
            continue
        parameter_key = param_by_label.get(_cell_text(row[0]).casefold()) or param_by_label.get(
            _normalize_label(row[0])
        )
        if not parameter_key or parameter_key not in allowed:
            continue
        for index, column_key in column_keys.items():
            if index >= len(row) or column_key not in known_columns:
                continue
            text = _cell_text(row[index])
            if not text:
                continue
            cell = workbook_service.get_or_create_cell(session, workbook, parameter_key, column_key)
            if cell.unified:
                continue
            cell.value = text
            cell.draft_value = None
            cell.status = "initial"
            cell.updated_by = username
            cell.updated_at = workbook_service._now()
            count += 1
    workbook.updated_at = workbook_service._now()
    session.flush()
    return count
