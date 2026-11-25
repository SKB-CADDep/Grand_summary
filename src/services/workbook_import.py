from __future__ import annotations

import re
from datetime import timedelta
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.models import Cell, CellChange, Workbook
from src.catalog import label_to_column_key, label_to_parameter_key, load_triangle_mapping, parameters
from src.services import workbooks as workbook_service
from src.services.decimals import normalize_decimal_commas

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
    if include_values and workbook_service.primary_sheet(source).id != source.id:
        base = workbook_service._base_cells(source)
        stored = {(item.parameter_key, item.column_key): item for item in source.cells}
        source_cells = (
            workbook_service.cells_from_issued_snapshot(source) if source.is_issued else list(source.cells)
        )
        copied: list[tuple[Cell, Cell]] = []
        for cell in source_cells:
            if not (cell.value or cell.draft_value or cell.hyperlink):
                continue
            if workbook_service.cell_matches_base(cell, base.get((cell.parameter_key, cell.column_key))):
                continue
            clone_cell = Cell(
                id=workbook_service._new_id(),
                workbook_id=clone.id,
                parameter_key=cell.parameter_key,
                column_key=cell.column_key,
                value=cell.value,
                draft_value=None,
                status="initial" if cell.value else "empty",
                hyperlink=cell.hyperlink,
                locked=bool(cell.locked),
                unified=bool(cell.unified),
                excel_highlight=bool(cell.excel_highlight) and not source.is_issued,
                updated_by=username,
                updated_at=workbook_service._now(),
            )
            session.add(clone_cell)
            persistent = stored.get((cell.parameter_key, cell.column_key))
            if persistent is not None:
                copied.append((persistent, clone_cell))
        session.flush()
        for persistent, clone_cell in copied:
            workbook_service.copy_cell_changes(session, persistent, clone_cell)
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


def read_sheet_grid(workbook: Workbook, excel_sheet) -> tuple[dict[tuple[str, str], str], set[str], set[str]]:
    rows = list(excel_sheet.iter_rows(values_only=True))
    grid: dict[tuple[str, str], str] = {}
    parameters_present: set[str] = set()
    columns_present: set[str] = set()
    if not rows:
        return grid, parameters_present, columns_present
    param_by_label = _parameter_lookup()
    col_by_label = label_to_column_key()
    header_index = _find_header_row(rows, col_by_label)
    header = rows[header_index]
    column_keys: dict[int, str] = {}
    allowed = workbook_service.editable_keys(workbook)
    known_columns = {item["key"] for item in workbook_service.workbook_columns(workbook)}
    for index, value in enumerate(header):
        text = _cell_text(value)
        if index == 0 or text.casefold() in SKIP_HEADER_LABELS:
            continue
        key = col_by_label.get(text.casefold()) or col_by_label.get(_normalize_label(text))
        if key and key in known_columns:
            column_keys[index] = key
            columns_present.add(key)
    for row in rows[header_index + 1 :]:
        if not row:
            continue
        parameter_key = param_by_label.get(_cell_text(row[0]).casefold()) or param_by_label.get(
            _normalize_label(row[0])
        )
        if not parameter_key or parameter_key not in allowed:
            continue
        parameters_present.add(parameter_key)
        for index, column_key in column_keys.items():
            if index >= len(row):
                continue
            text = normalize_decimal_commas(_cell_text(row[index])) or ""
            if text:
                grid[(parameter_key, column_key)] = text
    return grid, parameters_present, columns_present


def import_sheet(session: Session, workbook: Workbook, excel_sheet, username: str) -> tuple[int, dict[tuple[str, str], str], set[str], set[str]]:
    grid, parameters_present, columns_present = read_sheet_grid(workbook, excel_sheet)
    count = 0
    for (parameter_key, column_key), text in grid.items():
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
    workbook_service.compact_sheet(session, workbook)
    return count, grid, parameters_present, columns_present


def _sheet_value(
    grid: dict[tuple[str, str], str],
    parameters_present: set[str],
    columns_present: set[str],
    key: tuple[str, str],
    carried: str,
) -> str:
    parameter_key, column_key = key
    if parameter_key in parameters_present and column_key in columns_present:
        return grid.get(key, "")
    return carried


def record_excel_journal(
    session: Session,
    sheets: list[Workbook],
    grids: list[dict[tuple[str, str], str]],
    parameters_present: list[set[str]],
    columns_present: list[set[str]],
    username: str,
) -> int:
    if len(sheets) < 2:
        return 0
    primary = workbook_service.primary_sheet(sheets[0])
    primary_rows = session.query(Cell).filter(Cell.workbook_id == primary.id).all()
    primary_values = {(cell.parameter_key, cell.column_key): cell.value or "" for cell in primary_rows}
    primary_authors = {(cell.parameter_key, cell.column_key): cell.updated_by for cell in primary_rows}
    names = [sheet.sheet_name for sheet in sheets]
    moment = workbook_service._now()
    highlighted = 0
    for index, sheet in enumerate(sheets):
        if sheet.is_primary:
            continue
        keys: set[tuple[str, str]] = set(primary_values)
        for grid in grids[: index + 1]:
            keys.update(grid)
        stored = {
            (cell.parameter_key, cell.column_key): cell
            for cell in session.query(Cell).filter(Cell.workbook_id == sheet.id)
        }
        for key in keys:
            running = primary_values.get(key, "")
            changes: list[tuple[int, str, str]] = []
            for step in range(index + 1):
                value = _sheet_value(grids[step], parameters_present[step], columns_present[step], key, running)
                if value != running:
                    changes.append((step, running, value))
                    running = value
            if running == primary_values.get(key, "") or not changes:
                continue
            cell = stored.get(key)
            if cell is None:
                cell = workbook_service.get_or_create_cell(session, sheet, key[0], key[1])
                stored[key] = cell
            if cell.unified:
                continue
            cell.value = running or None
            cell.draft_value = None
            cell.status = "initial" if running else "empty"
            cell.excel_highlight = True
            cell.updated_by = username
            cell.updated_at = moment
            _append_excel_history(
                session,
                cell,
                key,
                primary_values.get(key, ""),
                primary_authors.get(key),
                changes,
                names,
                username,
                moment,
            )
            highlighted += 1
        session.flush()
        workbook_service.compact_sheet(session, sheet)
    return highlighted


def _append_excel_history(
    session: Session,
    cell: Cell,
    key: tuple[str, str],
    primary_value: str,
    primary_author: str | None,
    changes: list[tuple[int, str, str]],
    names: list[str],
    username: str,
    moment,
) -> None:
    del key
    already = session.query(CellChange.id).filter(CellChange.cell_id == cell.id).first()
    if already:
        return
    entries: list[tuple[str | None, str | None, str, str]] = []
    if primary_value:
        entries.append((None, primary_value, workbook_service.PRIMARY_ORIGIN_COMMENT, primary_author or "Основной лист"))
    for step, old, new in changes:
        entries.append((old or None, new or None, workbook_service.excel_sheet_comment(names[step]), username))
    start = moment - timedelta(seconds=len(entries))
    for offset, (old, new, comment, author) in enumerate(entries):
        session.add(
            CellChange(
                id=workbook_service._new_id(),
                cell_id=cell.id,
                author=author,
                created_at=start + timedelta(seconds=offset),
                old_value=old,
                new_value=new,
                comment=comment,
            )
        )
