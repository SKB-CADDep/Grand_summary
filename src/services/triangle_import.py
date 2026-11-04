from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from src.catalog import label_to_column_key, label_to_parameter_key, load_triangle_mapping


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


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
