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
        report_notes_json=getattr(source, "report_notes_json", None) or "[]",
    )
    session.add(clone)
    session.flush()
    if include_values:
        base = workbook_service._base_cells(source)
        skip_inherited = not workbook_service.sheet_is_frozen(source) and workbook_service.primary_sheet(source).id != source.id
        stored = {(item.parameter_key, item.column_key): item for item in source.cells}
        source_cells = (
            workbook_service.cells_from_issued_snapshot(source)
            if workbook_service.sheet_is_frozen(source)
            else list(source.cells)
        )
        copied: list[tuple[Cell, Cell]] = []
        for cell in source_cells:
            if not (cell.value or cell.draft_value or cell.hyperlink):
                continue
            if skip_inherited and workbook_service.cell_matches_base(cell, base.get((cell.parameter_key, cell.column_key))):
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
                excel_highlight=bool(cell.excel_highlight) and not workbook_service.sheet_is_frozen(source),
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


def apply_slice_to_main(
    session: Session,
    main: Workbook,
    values: dict[tuple[str, str], str],
    username: str,
    highlight_keys: set[tuple[str, str]] | None = None,
) -> None:
    moment = workbook_service._now()
    highlighted = highlight_keys or set()
    stored = {
        (cell.parameter_key, cell.column_key): cell
        for cell in session.query(Cell).filter(Cell.workbook_id == main.id)
    }
    for key, text in values.items():
        cell = stored.get(key)
        if cell is None:
            cell = workbook_service.get_or_create_cell(session, main, key[0], key[1])
            stored[key] = cell
        if cell.unified:
            continue
        cell.value = text or None
        cell.draft_value = None
        cell.status = "initial" if text else "empty"
        cell.excel_highlight = key in highlighted
        cell.updated_by = username
        cell.updated_at = moment
    main.show_change_highlight = True
    session.flush()


def record_excel_journal(
    session: Session,
    sheets: list[Workbook],
    grids: list[dict[tuple[str, str], str]],
    parameters_present: list[set[str]],
    columns_present: list[set[str]],
    username: str,
) -> int:
    if not sheets:
        return 0
    names = [sheet.sheet_name for sheet in sheets]
    moment = workbook_service._now()
    highlighted = 0
    running: dict[tuple[str, str], str] = {}
    main_highlight: set[tuple[str, str]] = set()
    main = workbook_service.working_sheet(sheets[0])
    main_stored = {
        (cell.parameter_key, cell.column_key): cell
        for cell in session.query(Cell).filter(Cell.workbook_id == main.id)
    }
    for index, sheet in enumerate(sheets):
        stamp = moment + timedelta(seconds=index)
        keys: set[tuple[str, str]] = set(running)
        keys.update(grids[index])
        for parameter_key in parameters_present[index]:
            for column_key in columns_present[index]:
                keys.add((parameter_key, column_key))
        stored = {
            (cell.parameter_key, cell.column_key): cell
            for cell in session.query(Cell).filter(Cell.workbook_id == sheet.id)
        }
        next_running = dict(running)
        changed_keys: set[tuple[str, str]] = set()
        for key in keys:
            previous = running.get(key, "")
            value = _sheet_value(grids[index], parameters_present[index], columns_present[index], key, previous)
            next_running[key] = value
            if value != previous:
                changed_keys.add(key)
        for key, value in next_running.items():
            cell = stored.get(key)
            if cell is None:
                cell = workbook_service.get_or_create_cell(session, sheet, key[0], key[1])
                stored[key] = cell
            if cell.unified:
                continue
            cell.value = value or None
            cell.draft_value = None
            cell.status = "initial" if value else "empty"
            cell.excel_highlight = False
            cell.updated_by = username
            cell.updated_at = stamp
            if key in changed_keys:
                previous = running.get(key, "")
                _append_period_history(
                    session,
                    cell,
                    previous,
                    value,
                    names[index],
                    username,
                    stamp,
                    unique=True,
                )
                main_cell = main_stored.get(key)
                if main_cell is None:
                    main_cell = workbook_service.get_or_create_cell(session, main, key[0], key[1])
                    main_stored[key] = main_cell
                if not main_cell.unified:
                    _append_period_history(
                        session,
                        main_cell,
                        previous,
                        value,
                        names[index],
                        username,
                        stamp,
                        unique=False,
                    )
                if index > 0:
                    main_highlight.add(key)
                highlighted += 1
        running = next_running
        session.flush()
        workbook_service.freeze_as_issued(sheet)
        session.flush()
    apply_slice_to_main(session, main, running, username, main_highlight if len(sheets) > 1 else set())
    workbook_service.order_project_sheets(workbook_service.list_sheet_workbooks(session, main))
    session.flush()
    return highlighted


def _append_period_history(
    session: Session,
    cell: Cell,
    old_value: str,
    new_value: str,
    sheet_name: str,
    username: str,
    moment,
    *,
    unique: bool = True,
) -> None:
    if unique and session.query(CellChange.id).filter(CellChange.cell_id == cell.id).first():
        return
    session.add(
        CellChange(
            id=workbook_service._new_id(),
            cell_id=cell.id,
            author=username,
            created_at=moment,
            old_value=old_value or None,
            new_value=new_value or None,
            comment=workbook_service.excel_sheet_comment(sheet_name),
        )
    )
