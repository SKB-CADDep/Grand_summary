from __future__ import annotations

import inspect

from desktop import run as desktop_run


def test_desktop_run_has_no_webengine():
    source = inspect.getsource(desktop_run)
    assert "QWebEngineView" not in source
    assert "QtWebEngine" not in source
    assert "require_frontend_build" not in source


def test_api_client_talks_to_app(client):
    from desktop.client import ApiClient

    api = ApiClient()
    try:
        me = api.me()
        assert "username" in me
        assert api.objects() == client.get("/api/objects").json()
    finally:
        api.close()


def test_native_ui_imports_without_webengine():
    from desktop.ui.window import MainWindow
    from desktop.ui.table_page import TablePage
    from desktop.ui.object_page import ObjectPage
    from desktop.ui.triangle_page import TrianglePage
    from desktop.ui.report_page import ReportHeader, ReportPage

    assert MainWindow is not None
    assert TablePage is not None
    assert ObjectPage is not None
    assert TrianglePage is not None
    assert ReportPage is not None
    source = inspect.getsource(MainWindow)
    assert "QWebEngineView" not in source
    assert "create_object" not in source
    page_source = inspect.getsource(ObjectPage)
    assert "object_create_requested" not in page_source
    assert "Создать объект" not in page_source
    from desktop.ui.chrome import TabStrip
    from desktop.ui.sheet_table import FrozenSheetTable
    tab_source = inspect.getsource(TabStrip)
    assert "setMinimumWidth" in tab_source
    table_source = inspect.getsource(TablePage)
    assert "Скрыть историю" in table_source
    assert "Показать историю" in table_source
    assert "Добавить ссылку" in table_source
    assert "структуру шапки" in table_source
    assert "edit_btn.setVisible" in table_source
    report_source = inspect.getsource(ReportPage)
    assert "Предпросмотр таблицы" in report_source
    assert "Ступени" in inspect.getsource(ReportHeader)
    triangle_source = inspect.getsource(TrianglePage)
    assert "Перенести выделенное" in triangle_source
    assert "triangle-subtabs" in triangle_source
    from desktop.ui.triangle_page import (
        SKIP_LEFT_COLUMNS,
        SKIP_TOP_ROWS,
        TriangleGrid,
        excel_from_body,
        is_source_cell,
    )

    assert SKIP_TOP_ROWS == 7
    assert SKIP_LEFT_COLUMNS == 1
    assert excel_from_body(0, 0) == (11, 2)
    assert is_source_cell(11, 2)
    assert not is_source_cell(10, 2)
    grid_source = inspect.getsource(TriangleGrid)
    assert "ExtendedSelection" in grid_source
    assert "triangle-grid-header" in grid_source
    assert "header_menu_requested" in inspect.getsource(FrozenSheetTable)
    assert FrozenSheetTable is not None
    from desktop.ui.table_page import _status_color
    from desktop.ui.style import COMPUTED, CONFIRMED, DRAFT

    assert _status_color({"status": "initial", "value": "120"}, "editable") is None
    assert _status_color({"status": "draft"}, "editable").name() == DRAFT
    assert _status_color({"status": "confirmed"}, "editable").name() == CONFIRMED
    assert _status_color({"status": "computed"}, "editable").name() == COMPUTED
    assert _status_color({"status": "empty"}, "section").name() == COMPUTED


def test_object_search_popup_closes_after_pick(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.object_page import ObjectPage

    page = ObjectPage()
    page.set_objects(
        [
            {"id": "1", "name": "Турбина А-1", "has_workbook": False},
            {"id": "2", "name": "Станция Север", "has_workbook": True},
        ],
        "",
    )
    page._on_typed("турбин")
    assert page.popup.isVisible()
    assert page.suggestions.count() == 1
    from PyQt6.QtGui import QPalette

    highlighted = page.suggestions.palette().color(QPalette.ColorRole.HighlightedText)
    assert highlighted.name() == "#263238"
    page._pick(page.suggestions.item(0))
    assert not page.popup.isVisible()
    assert page.search.text() == "Турбина А-1"
    app.processEvents()


def test_object_tab_keeps_full_label_when_selected(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.chrome import TabStrip
    from desktop.ui.style import APP_QSS

    app.setStyleSheet(APP_QSS)
    tabs = TabStrip()
    tabs.show()
    app.processEvents()
    button = tabs.buttons["object"]
    assert button.isChecked()
    metrics = QFontMetrics(button.font())
    assert button.minimumWidth() >= metrics.horizontalAdvance(button.text()) + 48


def test_triangle_grid_hides_preamble_and_keeps_excel_coords(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.triangle_page import TriangleGrid

    rows = [[f"{row}-{col}" for col in range(5)] for row in range(15)]
    grid = TriangleGrid()
    grid.fill("geometry", rows, {})
    assert grid.header.rowCount() == 3
    assert grid.header.columnCount() == 4
    assert grid.header.item(0, 0).text() == "7-1"
    assert grid.header.verticalHeader().isHidden()
    assert grid.body.item(0, 0).text() == "10-1"
    assert grid.body.verticalHeader().isHidden()
    grid.body.item(0, 1).setSelected(True)
    grid.body.item(1, 1).setSelected(True)
    selected = grid.current_sheet_selection()
    assert {"sheet_key": "geometry", "row": 11, "column": 3} in selected
    assert {"sheet_key": "geometry", "row": 12, "column": 3} in selected
    app.processEvents()


def test_triangle_caption_and_flow_path_number_column(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.triangle_page import TriangleGrid

    geometry = [[""] * 4 for _ in range(15)]
    geometry[7][1] = "Таблица  .1 - Основные геометрические данные"
    geometry[8][1] = "№ст"
    geometry[8][2] = "e,"
    geometry[10][1] = "2.0"
    geometry[10][2] = "100"
    grid = TriangleGrid()
    grid.fill("geometry", geometry, {}, [[9, 2, 10, 2], [9, 3, 9, 4]])
    assert grid.caption.text() == "Таблица .1 - Основные геометрические данные"
    assert not grid.caption.isHidden()
    assert grid.header.rowCount() == 2
    assert grid.header.item(0, 0).text() == "№ст"
    assert grid.header.rowSpan(0, 0) == 2
    assert grid.header.columnSpan(0, 1) == 2
    assert grid.header.verticalHeader().isHidden()
    assert grid.body.item(0, 0).text() == "2.0"
    assert grid.header.rowHeight(0) == 24
    assert grid.header.wordWrap() is False

    flow = [[""] * 4 for _ in range(15)]
    flow[6][1] = "Таблица   . Параметры проточной части"
    flow[7][1] = "№"
    flow[7][2] = "Направляющая лопатка"
    flow[10][1] = "2"
    flow[10][2] = "2170ТЧ"
    grid.fill("flow_path", flow, {}, [[8, 3, 8, 4], [8, 2, 9, 2]])
    assert grid.caption.text() == "Таблица . Параметры проточной части"
    assert grid.header.item(0, 0).text() == "№"
    assert grid.header.rowSpan(0, 0) == 2
    assert grid.header.item(0, 1).text() == "Направляющая лопатка"
    assert grid.header.columnSpan(0, 1) == 2
    assert grid.body.item(0, 0).text() == "2"
    assert grid.body.item(0, 1).text() == "2170ТЧ"
    assert grid.body.verticalHeader().isHidden()
    grid.body.item(0, 1).setSelected(True)
    assert {"sheet_key": "flow_path", "row": 11, "column": 3} in grid.current_sheet_selection()
    app.processEvents()


def test_material_cell_editor_filters_typed_text(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import OPTIONS_ROLE, CellDelegate

    table = QTableWidget(1, 1)
    item = QTableWidgetItem("")
    item.setData(OPTIONS_ROLE, ["12Х13", "12Х18Н10Т", "20Х13", "Сталь 20"])
    table.setItem(0, 0, item)
    editor = CellDelegate(table).createEditor(table, None, table.model().index(0, 0))
    completer = editor.completer()
    assert completer is not None
    assert completer.filterMode() == Qt.MatchFlag.MatchContains
    assert editor.count() == 5
    completer.setCompletionPrefix("12х")
    assert completer.completionCount() == 2
    completer.setCompletionPrefix("сталь")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "Сталь 20"
    app.processEvents()
