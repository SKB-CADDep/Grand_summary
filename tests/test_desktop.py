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
    assert grid.header.verticalHeaderItem(0).text() == "8"
    assert grid.body.item(0, 0).text() == "10-1"
    assert grid.body.verticalHeaderItem(0).text() == "11"
    grid.body.item(0, 1).setSelected(True)
    grid.body.item(1, 1).setSelected(True)
    selected = grid.current_sheet_selection()
    assert {"sheet_key": "geometry", "row": 11, "column": 3} in selected
    assert {"sheet_key": "geometry", "row": 12, "column": 3} in selected
    app.processEvents()
