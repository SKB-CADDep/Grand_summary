from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from backend.models import Cell, TriangleSheet, Workbook
from src.catalog import label_to_column_key, label_to_parameter_key, load_triangle_mapping
from src.services import workbooks as workbook_service
from src.services.journal import add_audit


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _triangle_cell_text(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return _cell_text(value)
        if rounded == 0:
            return "0"
        text = format(rounded, "f").rstrip("0").rstrip(".")
        return text.replace(".", ",")
    return _cell_text(value)


def _triangle_angle_cell_text(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            precise = Decimal(str(value))
        except InvalidOperation:
            return _cell_text(value)
        return format(precise.normalize(), "f").replace(".", ",")
    return _cell_text(value)


TRIANGLE_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "geometry": (
        "nst", "eps_pct", "fs_dm2", "l1_mm", "sina1", "d1_mm", "fl_dm2", "l2_mm",
        "sinb2", "d2_mm", "ruz", "rur", "rud", "dekv_dia", "buz", "bur",
        "dekv_band", "tipu_dia", "tipu_band", "th", "tr",
    ),
    "flow_path": (
        "nst", "th", "dk_n", "l1_mm", "hord_h", "zh", "ab1_h", "fs_dm2", "tr",
        "dk_r", "l2_mm", "hord_r", "zr", "ab1_r", "fl_dm2",
    ),
}

TRIANGLE_PARAMETER_MAP: dict[str, dict[str, str]] = {
    "geometry": {
        "eps_pct": "r011",
        "fs_dm2": "r009",
        "l1_mm": "r010",
        "sina1": "r008",
        "d1_mm": "r014",
        "fl_dm2": "r052",
        "l2_mm": "r047",
        "sinb2": "r051",
        "d2_mm": "r049",
    },
    "flow_path": {
        "dk_n": "r013",
        "hord_h": "r012",
        "zh": "r015",
        "ab1_h": "r007",
        "fs_dm2": "r009",
        "dk_r": "r048",
        "zr": "r050",
        "fl_dm2": "r052",
    },
}

TRIANGLE_COORDINATE_MAP: dict[str, dict[int, tuple[tuple[str, str], ...]]] = {
    "geometry": {
        3: (("r011", "percentage_fraction"),),
        4: (("r009", "area"),),
        6: (("r008", "identity"),),
        7: (("r014", "identity"),),
        8: (("r052", "area"),),
        10: (("r051", "identity"),),
        11: (("r049", "identity"),),
    },
    "flow_path": {
        3: (("r006", "identity"),),
        4: (("r013", "identity"),),
        5: (("r010", "identity"),),
        6: (("r012", "identity"),),
        7: (("r015", "identity"),),
        8: (("r007", "identity"),),
        10: (("r043", "identity"),),
        11: (("r048", "identity"),),
        12: (("r047", "identity"),),
        14: (("r050", "identity"),),
        17: (("r060", "profile_type"), ("r061", "tail_drawing")),
        23: (("r083", "identity"),),
        24: (("r022", "identity"),),
        28: (("r026", "identity"),),
        29: (("r035", "identity"),),
        31: (("r036", "identity"),),
    },
}

_AREA_CONVERSION = Decimal("10000")


def triangle_parameter_mapping(sheet_key: str) -> dict[str, str]:
    return dict(TRIANGLE_PARAMETER_MAP.get(sheet_key, {}))


def triangle_coordinate_mapping(sheet_key: str) -> dict[str, list[str]]:
    return {
        str(column): [parameter_key for parameter_key, _transform in targets]
        for column, targets in TRIANGLE_COORDINATE_MAP.get(sheet_key, {}).items()
    }


def _normalise_stage(value: str) -> str:
    text = re.sub(r"\s+", "", value).casefold().replace("ё", "е")
    try:
        return format(Decimal(text.replace(",", ".")).normalize(), "f")
    except InvalidOperation:
        return text


def _converted_triangle_value(field_key: str, value: str) -> str:
    if field_key not in {"fs_dm2", "fl_dm2"}:
        return value
    try:
        converted = Decimal(value.replace(",", ".")) * _AREA_CONVERSION
    except InvalidOperation as exc:
        raise ValueError(f"Ожидалось числовое значение для {field_key}") from exc
    return format(converted.normalize(), "f")


def _decimal_degrees_to_dms(value: str) -> str:
    try:
        degrees_value = Decimal(value.replace(",", "."))
        if not degrees_value.is_finite():
            raise InvalidOperation
        total_seconds = (abs(degrees_value) * Decimal(3600)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    except InvalidOperation as exc:
        raise ValueError("Ожидалось числовое значение для угла α'уст") from exc
    degrees, remainder = divmod(int(total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    sign = "-" if degrees_value < 0 else ""
    return f'{sign}{degrees}°{minutes:02d}\'{seconds:02d}"'


def _transform_coordinate_value(transform: str, value: str) -> str:
    if transform == "area":
        return _converted_triangle_value("fs_dm2", value)
    if transform == "percentage_fraction":
        try:
            percentage = Decimal(value.strip().removesuffix("%").strip().replace(",", "."))
            if not percentage.is_finite():
                raise InvalidOperation
            fraction = percentage / Decimal(100)
        except InvalidOperation as exc:
            raise ValueError("Ожидалось числовое значение для парциальности (e)") from exc
        return format(fraction.normalize(), "f").replace(".", ",")
    if transform == "profile_type":
        match = re.match(r"\s*([A-Za-zА-Яа-яЁё]+)", value)
        return match.group(1) if match else ""
    if transform == "tail_drawing":
        dashed_drawing = re.search(r"[A-Za-zА-Яа-яЁё]+\s*-\s*\d+", value)
        if dashed_drawing:
            return re.sub(r"\s+", "", dashed_drawing.group(0))
        return re.sub(r"\D", "", value)
    return value


def parse_triangle_sheets(file_obj) -> list[dict[str, Any]]:
    required_sheets = {
        "геом. данные": ("geometry", "Геом. данные"),
        "проточная часть": ("flow_path", "Проточная часть"),
    }
    try:
        workbook = load_workbook(file_obj, data_only=True)
    except Exception as exc:
        raise ValueError("Не удалось прочитать Excel-файл треугольников") from exc

    try:
        available = {sheet.title.strip().casefold(): sheet for sheet in workbook.worksheets}
        missing = [display_name for normalized, (_, display_name) in required_sheets.items() if normalized not in available]
        if missing:
            raise ValueError(f"В файле отсутствуют обязательные листы: {', '.join(missing)}")

        parsed: list[dict[str, Any]] = []
        for normalized, (sheet_key, display_name) in required_sheets.items():
            sheet = available[normalized]
            rows = []
            for row_number, row in enumerate(
                sheet.iter_rows(
                    min_row=1,
                    max_row=sheet.max_row or 1,
                    max_col=sheet.max_column or 1,
                    values_only=True,
                ),
                start=1,
            ):
                formatted_row = []
                for column_number, cell in enumerate(row, start=1):
                    preserve_angle_precision = (
                        sheet_key == "flow_path" and row_number >= 11 and column_number == 8
                    )
                    formatted_row.append(
                        _triangle_angle_cell_text(cell)
                        if preserve_angle_precision
                        else _triangle_cell_text(cell)
                    )
                rows.append(formatted_row)
            merged_ranges = [
                [cell_range.min_row, cell_range.min_col, cell_range.max_row, cell_range.max_col]
                for cell_range in sheet.merged_cells.ranges
            ]
            parsed.append({
                "key": sheet_key,
                "name": display_name,
                "rows": rows,
                "merged_ranges": merged_ranges,
                "parameter_mapping": triangle_parameter_mapping(sheet_key),
                "coordinate_mapping": triangle_coordinate_mapping(sheet_key),
            })
        return parsed
    finally:
        workbook.close()


def parse_triangle_excel(path: Path) -> dict[str, dict[str, str]]:
    """Разбирает xlsx/xlsm тепловиков: подписи в колонке A, ступени в шапке."""
    mapping = load_triangle_mapping()
    aliases = {str(key).casefold(): value for key, value in mapping.get("aliases", {}).items()}
    param_by_label = label_to_parameter_key()
    param_by_label.update(aliases)
    col_by_label = label_to_column_key()

    wb = load_workbook(path, data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {}

    header_row_index = _find_header_row(rows, col_by_label)
    header = rows[header_row_index]
    column_keys: dict[int, str] = {}
    for index, value in enumerate(header):
        if index == 0:
            continue
        key = col_by_label.get(_cell_text(value).casefold())
        if key:
            column_keys[index] = key

    result: dict[str, dict[str, str]] = {}
    for row in rows[header_row_index + 1 :]:
        if not row:
            continue
        label = _cell_text(row[0]).casefold()
        if not label:
            continue
        parameter_key = param_by_label.get(label)
        if not parameter_key:
            continue
        for index, column_key in column_keys.items():
            if index >= len(row):
                continue
            text = _cell_text(row[index])
            if text == "":
                continue
            result.setdefault(parameter_key, {})[column_key] = text
    return result


def _find_header_row(rows: list[tuple], col_by_label: dict[str, str]) -> int:
    best_index = 0
    best_score = -1
    for index, row in enumerate(rows[:15]):
        score = 0
        for value in row[1:]:
            if col_by_label.get(_cell_text(value).casefold()):
                score += 1
        if score > best_score:
            best_score = score
            best_index = index
    if best_score <= 0:
        configured = load_triangle_mapping().get("header_row", 3)
        return max(int(configured) - 1, 0)
    return best_index


def sync_triangle_data(
    session: Session,
    target_workbook: Workbook,
    username: str,
    mode: str,
    selected_cells: list[dict] | None = None,
    target_parameter_key: str | None = None,
) -> dict[str, Any]:
    root = target_workbook.parent or target_workbook
    stored_sheets = (
        session.query(TriangleSheet)
        .filter(TriangleSheet.workbook_id == root.id)
        .all()
    )
    imported = {item.sheet_key: json.loads(item.data_json) for item in stored_sheets}
    if not imported:
        raise ValueError("Сначала импортируйте треугольники")
    if mode not in {"all", "selected"}:
        raise ValueError("Неизвестный режим синхронизации")
    parameters_by_key = {
        parameter["key"]: parameter
        for parameter in workbook_service.workbook_parameters(target_workbook)
    }
    editable_parameter_keys = {
        key for key, parameter in parameters_by_key.items()
        if parameter.get("row_kind") == "editable"
    }
    columns_by_key = {
        column["key"]: column
        for column in workbook_service.workbook_columns(target_workbook)
    }
    if target_parameter_key is not None:
        if mode != "selected":
            raise ValueError("Целевой параметр можно задать только для выделенных ячеек")
        if target_parameter_key not in editable_parameter_keys:
            raise ValueError("Выберите существующий редактируемый параметр ИД")

    stage_columns: dict[str, str] = {}
    stage_lookup_by_row: dict[tuple[str, int], str | None] = {}
    ambiguous_stages: set[str] = set()
    for column in columns_by_key.values():
        normalized = _normalise_stage(str(column.get("label", "")))
        if normalized in stage_columns:
            ambiguous_stages.add(normalized)
        else:
            stage_columns[normalized] = column["key"]
    for label in ambiguous_stages:
        stage_columns.pop(label, None)

    desired: dict[tuple[str, str], tuple[str, str, str]] = {}
    conflicts: set[tuple[str, str]] = set()
    unsupported: set[str] = set()
    skipped = 0

    def add_target(
        sheet_key: str,
        row_number: int,
        parameter_key: str,
        value: str,
        source_label: str,
        transform: str | None = None,
    ) -> None:
        nonlocal skipped
        sheet = imported.get(sheet_key)
        if sheet is None or row_number < 11:
            skipped += 1
            return
        rows = sheet.get("rows", [])
        if row_number > len(rows):
            skipped += 1
            return
        row = rows[row_number - 1]
        stage_cache_key = (sheet_key, row_number)
        if stage_cache_key not in stage_lookup_by_row:
            stage_value = _cell_text(row[1] if len(row) > 1 else "")
            stage_lookup_by_row[stage_cache_key] = stage_columns.get(_normalise_stage(stage_value))
        column_key = stage_lookup_by_row[stage_cache_key]
        if not column_key:
            skipped += 1
            return
        try:
            if parameter_key == "r007":
                converted = _decimal_degrees_to_dms(value)
            else:
                converted = (
                    _transform_coordinate_value(transform, value)
                    if transform
                    else _converted_triangle_value(source_label, value)
                )
        except ValueError:
            skipped += 1
            return
        if not converted:
            skipped += 1
            return
        target = (parameter_key, column_key)
        source = (converted, sheet.get("name", sheet_key), source_label)
        previous = desired.get(target)
        if previous and previous[0] != converted:
            conflicts.add(target)
        else:
            desired[target] = source

    def add_source(
        sheet_key: str,
        row_number: int,
        column_number: int,
        custom_parameter_key: str | None = None,
    ) -> None:
        nonlocal skipped
        field_keys = TRIANGLE_SOURCE_FIELDS.get(sheet_key, ())
        if row_number < 11 or column_number < 3:
            skipped += 1
            return
        rows = imported.get(sheet_key, {}).get("rows", [])
        if row_number > len(rows):
            skipped += 1
            return
        row = rows[row_number - 1]
        value = _cell_text(row[column_number - 1] if column_number - 1 < len(row) else "")
        field_index = column_number - 2
        field_key = field_keys[field_index] if field_index < len(field_keys) else None
        parameter_key = TRIANGLE_PARAMETER_MAP.get(sheet_key, {}).get(field_key or "")
        source_label = field_key or f"{get_column_letter(column_number)}{row_number}"
        if parameter_key:
            add_target(sheet_key, row_number, parameter_key, value, source_label)
            return
        if custom_parameter_key:
            add_target(sheet_key, row_number, custom_parameter_key, value, source_label)
            return
        if field_key:
            unsupported.add(field_key)
        skipped += 1

    def add_coordinate_source(sheet_key: str, row_number: int, column_number: int) -> None:
        nonlocal skipped
        targets = TRIANGLE_COORDINATE_MAP.get(sheet_key, {}).get(column_number)
        rows = imported.get(sheet_key, {}).get("rows", [])
        if not targets or row_number < 11 or row_number > len(rows):
            skipped += 1
            return
        row = rows[row_number - 1]
        value = _cell_text(row[column_number - 1] if column_number - 1 < len(row) else "")
        source_label = f"{get_column_letter(column_number)}{row_number}"
        for parameter_key, transform in targets:
            add_target(sheet_key, row_number, parameter_key, value, source_label, transform)

    if mode == "selected":
        for item in selected_cells or []:
            sheet_key = str(item.get("sheet_key", ""))
            row_number = int(item.get("row", 0))
            column_number = int(item.get("column", 0))
            if column_number in TRIANGLE_COORDINATE_MAP.get(sheet_key, {}):
                add_coordinate_source(sheet_key, row_number, column_number)
            else:
                add_source(sheet_key, row_number, column_number, target_parameter_key)
    else:
        for sheet_key, sheet in imported.items():
            coordinate_columns = TRIANGLE_COORDINATE_MAP.get(sheet_key, {})
            for row_number in range(11, len(sheet.get("rows", [])) + 1):
                row = sheet["rows"][row_number - 1]
                for column_number in coordinate_columns:
                    if column_number <= len(row) and _cell_text(row[column_number - 1]):
                        add_coordinate_source(sheet_key, row_number, column_number)

    for target in conflicts:
        desired.pop(target, None)

    if not desired:
        return {
            "updated": 0,
            "cleared": 0,
            "skipped": skipped,
            "unsupported_fields": sorted(unsupported),
            "conflicts": len(conflicts),
        }

    planned: list[tuple[Cell, str, str, str, str]] = []
    for (parameter_key, column_key), (value, source_name, field_key) in desired.items():
        cell = workbook_service.get_or_create_cell(session, target_workbook, parameter_key, column_key)
        if cell.unified:
            skipped += 1
            continue
        if parameter_key not in parameters_by_key:
            parameters_by_key[parameter_key] = workbook_service.resolve_parameter(target_workbook, parameter_key)
        parameter = parameters_by_key[parameter_key]
        if not parameter or parameter.get("row_kind") not in {"editable"}:
            raise ValueError("Ячейка недоступна для редактирования")
        column = columns_by_key.get(column_key)
        if column is None:
            raise ValueError("Неизвестная колонка")
        if cell.locked:
            raise ValueError("Ячейка заблокирована правилом унификации")
        if cell.status == "draft":
            raise ValueError(f"Сначала сохраните или отмените черновик {parameter_key}/{column_key}")
        if not value:
            continue
        if cell.value == value and cell.status == "triangle":
            continue
        parameter_label = parameter.get("label", parameter_key)
        column_label = column["label"]
        comment = (
            f"Синхронизировано из треугольников «{source_name}», параметр «{parameter_label}» "
            f"({field_key}), ступень «{column_label}»."
            if value
            else "Очищено при полной синхронизации с треугольниками: значение в импортированных данных отсутствует."
        )
        planned.append((cell, value, comment, parameter_label, column_label))

    if not planned:
        return {
            "updated": 0,
            "cleared": 0,
            "skipped": skipped,
            "unsupported_fields": sorted(unsupported),
            "conflicts": len(conflicts),
        }

    workbook_service.create_version(
        session,
        target_workbook,
        username,
        "triangle_import",
        "Перед синхронизацией данных из треугольников",
    )
    updated = 0
    cleared = 0
    for cell, value, comment, _parameter_label, _column_label in planned:
        workbook_service.confirm_cell(
            session,
            target_workbook,
            cell.parameter_key,
            cell.column_key,
            username,
            comment,
            value=value,
            system=True,
            existing_cell=cell,
        )
        if value:
            cell.status = "triangle"
            updated += 1
        else:
            cell.status = "empty"
            cleared += 1

    for cell, value, _comment, _parameter_label, _column_label in planned:
        if value:
            workbook_service.apply_rules(
                session, target_workbook, cell.parameter_key, cell.column_key, username
            )

    add_audit(
        session,
        actor=username,
        action="triangle_sync",
        workbook=target_workbook,
        comment="Синхронизация значений из импортированных треугольников",
        summary=f"Из треугольников: обновлено {updated}, очищено {cleared}, пропущено {skipped + len(conflicts)}",
    )
    session.flush()
    return {
        "updated": updated,
        "cleared": cleared,
        "skipped": skipped,
        "unsupported_fields": sorted(unsupported),
        "conflicts": len(conflicts),
    }
