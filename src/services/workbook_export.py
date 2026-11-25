from __future__ import annotations

import json
from io import BytesIO

from openpyxl import Workbook as ExcelWorkbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from backend.models import TriangleSheet, Workbook
from src.services import workbooks as workbook_service
from src.services.decimals import normalize_decimal_commas
from src.services.triangle_import import triangle_sheet_sort_key
from src.services.workbooks import _display


def _fill_id_sheet(sheet: Worksheet, workbook: Workbook, title: str) -> None:
    sheet.title = (title or "Исходные данные")[:31]
    parameters = workbook_service.workbook_parameters(workbook)
    columns = workbook_service.workbook_columns(workbook)
    sheet.cell(1, 1, "Наименование параметра")
    sheet.cell(1, 2, "Ед. изм.")
    sheet.cell(1, 3, "")
    for index, column in enumerate(columns, start=4):
        sheet.cell(1, index, column.get("label") or column["key"])
    cells = {(cell.parameter_key, cell.column_key): cell for cell in workbook_service.effective_cells(workbook)}
    for row_index, parameter in enumerate(parameters, start=2):
        sheet.cell(row_index, 1, parameter.get("label") or parameter["key"])
        sheet.cell(row_index, 2, parameter.get("unit") or "")
        for col_index, column in enumerate(columns, start=4):
            cell = cells.get((parameter["key"], column["key"]))
            sheet.cell(row_index, col_index, _display(cell) if cell else None)


def _fill_triangle_sheet(sheet: Worksheet, stored: TriangleSheet) -> None:
    sheet.title = (stored.sheet_name or stored.sheet_key)[:31]
    data = json.loads(stored.data_json or "{}")
    for row_index, row in enumerate(data.get("rows") or [], start=1):
        for col_index, value in enumerate(row, start=1):
            if isinstance(value, str):
                value = normalize_decimal_commas(value)
            sheet.cell(row_index, col_index, value)


def build_workbook_export(session: Session, workbook: Workbook, scope: str) -> bytes:
    excel = ExcelWorkbook()
    first = True

    def next_sheet() -> Worksheet:
        nonlocal first
        if first:
            first = False
            return excel.active
        return excel.create_sheet()

    if scope == "current":
        _fill_id_sheet(next_sheet(), workbook, workbook.sheet_name)
    else:
        root = workbook.parent or workbook
        for item in workbook_service.list_sheet_workbooks(session, root):
            _fill_id_sheet(next_sheet(), item, item.sheet_name)
        triangles = (
            session.query(TriangleSheet)
            .filter(TriangleSheet.workbook_id == root.id)
            .all()
        )
        triangles.sort(
            key=lambda stored: triangle_sheet_sort_key(json.loads(stored.data_json or "{}"))
        )
        for stored in triangles:
            _fill_triangle_sheet(next_sheet(), stored)

    buffer = BytesIO()
    excel.save(buffer)
    return buffer.getvalue()
