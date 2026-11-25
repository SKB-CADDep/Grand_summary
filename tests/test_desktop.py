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
    assert "clear_highlight_btn" not in table_source
    assert "Снять оранжевую подсветку" in table_source
    assert "edit_btn.setVisible" in table_source
    report_source = inspect.getsource(ReportPage)
    assert "Предпросмотр таблицы" in report_source
    from desktop.ui.report_page import PreviewHeader, _COLUMN_GROUP_TITLES

    assert _COLUMN_GROUP_TITLES["stage"] == "Ступени"
    assert "Ступени" in inspect.getsource(PreviewHeader)
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
    from desktop.ui.style import COMPUTED, CONFIRMED, DRAFT, IMPORTED

    assert _status_color({"status": "initial", "value": "120"}, "editable") is None
    assert _status_color({"status": "draft"}, "editable").name() == DRAFT
    assert _status_color({"status": "confirmed"}, "editable").name() == CONFIRMED
    assert _status_color({"status": "initial", "excel_highlight": True}, "editable").name() == IMPORTED
    assert _status_color({"status": "initial", "excel_highlight": True}, "editable", show_changes=False) is None
    assert _status_color({"status": "computed"}, "editable").name() == COMPUTED
    assert _status_color({"status": "empty"}, "section").name() == COMPUTED


def test_clear_orange_highlight_is_a_context_action(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMenu

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import TablePage

    page = TablePage()
    page.can_write = True
    hidden = QMenu()
    page._add_clear_highlight_action(hidden)
    assert hidden.actions() == []
    page._cells = {"r010:s1": {"excel_highlight": True}}
    shown = QMenu()
    page._add_clear_highlight_action(shown)
    labels = [action.text() for action in shown.actions() if action.text()]
    assert labels == ["Снять оранжевую подсветку"]
    page.close()
    hidden.close()
    shown.close()
    app.processEvents()


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


def test_combo_boxes_show_a_dropdown_arrow(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QComboBox

    app = QApplication.instance() or QApplication([])
    from desktop.ui.style import APP_QSS

    app.setStyleSheet(APP_QSS)

    def has_arrow(box: QComboBox) -> bool:
        box.resize(220, 40)
        box.show()
        app.processEvents()
        image = box.grab().toImage()
        for x in range(image.width() - 28, image.width() - 6):
            for y in range(8, image.height() - 8):
                color = image.pixelColor(x, y)
                if color.alpha() > 180 and color.red() < 140 and color.green() < 150 and color.blue() < 160:
                    return True
        return False

    plain = QComboBox()
    plain.addItems(["Исходные данные по проточной части", "Исходные данные по облопачиванию"])
    material = QComboBox()
    material.setEditable(True)
    material.addItems(["Сталь 20", "Сталь 15Х1М1Ф"])
    assert has_arrow(plain)
    assert has_arrow(material)
    plain.close()
    material.close()


def _rendered(widget):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image)
    return image


def test_combo_popup_corners_are_rounded(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QComboBox

    app = QApplication.instance() or QApplication([])
    from desktop.ui.style import APP_QSS, install_rounded_popups
    from desktop.ui.table_page import _option_editor

    app.setStyleSheet(APP_QSS)
    install_rounded_popups(app)
    box = QComboBox()
    box.addItems(["Исходные данные по проточной части", "Исходные данные по облопачиванию"])
    box.resize(240, 36)
    box.show()
    box.showPopup()
    app.processEvents()
    image = _rendered(box.view().window())
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(image.width() - 1, 0).alpha() == 0
    middle = image.pixelColor(image.width() // 2, image.height() // 2)
    assert middle.alpha() == 255
    assert middle.name() in {"#ffffff", "#dbeafe"}
    box.hidePopup()
    box.close()

    material = _option_editor(None, ["12Х18Н10Т", "Сталь 20", "15Х1М1Ф"])
    material.resize(260, 36)
    material.show()
    app.processEvents()
    field = material.grab().toImage()
    assert field.pixelColor(16, field.height() // 2).name() == "#ffffff"
    material.setEditText("ст")
    material.completer().complete()
    app.processEvents()
    matches = _rendered(material.completer().popup())
    assert matches.pixelColor(0, 0).alpha() == 0
    choice = matches.pixelColor(matches.width() // 2, matches.height() // 2)
    assert choice.alpha() == 255
    assert choice.name() == "#ffffff"
    material.close()


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


def test_triangle_grid_hides_trailing_empty_columns(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.triangle_page import TriangleGrid

    rows = [[""] * 12 for _ in range(12)]
    rows[10][1] = "1"
    rows[10][3] = "800"
    grid = TriangleGrid()
    grid.fill("source", rows, {})
    assert grid.body.columnCount() == 3
    assert grid.body.item(0, 0).text() == "1"
    assert grid.body.item(0, 2).text() == "800"

    rows[7][1] = "Шапка"
    grid.fill("source", rows, {}, [[8, 2, 8, 6]])
    assert grid.header.columnCount() == 5
    app.processEvents()


def test_triangle_designation_tooltip_names_id_parameter(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.triangle_page import TrianglePage

    rows = [[""] * 6 for _ in range(12)]
    rows[7][2] = "Направляющая лопатка"
    rows[8][2] = "e,"
    rows[8][3] = "хв-ка"
    rows[9][2] = "мм"
    rows[10][2] = "100"
    page = TrianglePage()
    page.set_data(
        [
            {
                "key": "geometry",
                "name": "Геом. данные",
                "rows": rows,
                "merged_ranges": [[8, 3, 8, 4]],
                "coordinate_mapping": {"3": ["r011"], "4": ["r060", "r061"]},
            }
        ],
        [],
        False,
        False,
    )
    assert page.grid.header.item(1, 1).toolTip() == ""
    page.set_catalog(
        {
            "parameters": [
                {"key": "r011", "label": "Парциальность (e,)", "row_kind": "editable"},
                {"key": "r060", "label": "Тип (Профиль)", "row_kind": "editable"},
                {"key": "r061", "label": "Чертеж профиля хвостовика (профиль)", "row_kind": "editable"},
            ]
        }
    )
    assert page.grid.header.item(1, 1).text() == "e,"
    assert page.grid.header.item(1, 1).toolTip() == "Таблица ИД: Парциальность"
    assert page.grid.header.item(2, 1).toolTip() == "Таблица ИД: Парциальность"
    assert page.grid.header.item(0, 1).toolTip() == ""
    assert "Тип" in page.grid.header.item(1, 2).toolTip()
    assert "Чертеж профиля хвостовика" in page.grid.header.item(1, 2).toolTip()
    assert page.grid.body.item(0, 1).toolTip() == ""
    app.processEvents()


def test_unmapped_parameter_picker_is_a_searchable_tree(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.triangle_page import TrianglePage

    page = TrianglePage()
    page.set_catalog(
        {
            "parameters": [
                {"key": "r005", "label": "Сопловая лопатка:", "row_kind": "section", "indent": 0},
                {
                    "key": "r007",
                    "label": "Угол установки профиля в корневом сечении (α'уст)",
                    "row_kind": "editable",
                    "indent": 1,
                },
                {
                    "key": "r010",
                    "label": "Высота сопловой лопатки (L'), мм",
                    "row_kind": "editable",
                    "indent": 1,
                    "unit": "мм",
                },
                {"key": "r017", "label": "Диафрагма:", "row_kind": "section", "indent": 0},
                {"key": "r021", "label": "Тип исполнения", "row_kind": "editable", "indent": 1},
            ]
        }
    )
    combo = page.param_combo
    assert combo.currentData() == ""
    assert combo._label.text() == "Не задан"
    assert combo._tree.topLevelItemCount() == 3
    nozzle = combo._tree.topLevelItem(1)
    diaphragm = combo._tree.topLevelItem(2)
    assert nozzle.text(0) == "Сопловая лопатка:"
    assert nozzle.childCount() == 2
    assert nozzle.isExpanded() is False
    nozzle.setExpanded(True)
    assert nozzle.isExpanded() is True
    nozzle.setExpanded(False)
    assert nozzle.isExpanded() is False
    combo._item_clicked(nozzle, 0)
    assert combo.currentData() == ""
    height = nozzle.child(1)
    assert "Высота сопловой лопатки" in height.text(0)
    combo._search.setText("высота")
    assert nozzle.isHidden() is False
    assert nozzle.isExpanded() is True
    assert nozzle.child(0).isHidden() is True
    assert height.isHidden() is False
    assert diaphragm.isHidden() is True
    combo._item_clicked(height, 0)
    assert combo.currentData() == "r010"
    assert "Высота сопловой лопатки" in combo._label.text()
    combo._search.setText("")
    combo._item_clicked(combo._tree.topLevelItem(0), 0)
    assert combo.currentData() == ""
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
    assert grid.header_stage.item(0, 0).text() == "№ст"
    assert grid.header_stage.rowSpan(0, 0) == 2
    assert grid.header_stage.columnCount() == 1
    assert grid.body_stage.item(0, 0).text() == "2.0"
    grid.resize(220, 240)
    grid.body.setColumnWidth(1, 600)
    grid.header.setColumnWidth(1, 600)
    grid.show()
    app.processEvents()
    pinned = grid.body_stage.x()
    grid.body.horizontalScrollBar().setValue(grid.body.horizontalScrollBar().maximum())
    app.processEvents()
    assert grid.body_stage.x() == pinned
    assert grid.body_stage.isVisible()
    assert grid.body_stage.item(0, 0).text() == "2.0"
    assert grid.header_stage.item(0, 0).text() == "№ст"
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
    assert grid.header_stage.item(0, 0).text() == "№"
    assert grid.body_stage.item(0, 0).text() == "2"
    assert grid.header.rowSpan(0, 0) == 2
    assert grid.header.item(0, 1).text() == "Направляющая лопатка"
    assert grid.header.columnSpan(0, 1) == 2
    assert grid.body.item(0, 0).text() == "2"
    assert grid.body.item(0, 1).text() == "2170ТЧ"
    flow[7][2] = "Площадь, мм2"
    flow[10][2] = "12Х13"
    grid.fill("flow_path", flow, {}, [[8, 3, 8, 4], [8, 2, 9, 2]])
    assert grid.header.item(0, 1).text() == "Площадь, мм²"
    assert grid.body.item(0, 1).text() == "12Х13"
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


def test_id_table_link_cell_uses_pointing_hand(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import DATA_COLUMN, TablePage

    page = TablePage()
    page.set_data(
        object_name="Объект",
        catalog={
            "columns": [{"key": "s1", "label": "1"}],
            "parameters": [
                {"key": "r010", "label": "Высота сопловой лопатки (L'), мм", "row_kind": "editable", "indent": 1, "unit": "мм"},
            ],
        },
        workbook={
            "id": "sheet",
            "is_primary": False,
            "is_issued": False,
            "cells": [
                {
                    "parameter_key": "r010",
                    "column_key": "s1",
                    "value": "120",
                    "display": "120",
                    "hyperlink": "https://example.test/drawing",
                    "status": "confirmed",
                }
            ],
        },
        unsaved=[],
        sheets=[{"id": "sheet", "name": "Лист", "is_primary": False}],
        can_write=True,
        busy=False,
    )
    page._cell_entered(0, DATA_COLUMN)
    assert page.table.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert page.table.item(0, DATA_COLUMN).toolTip() == "Нажмите Ctrl+ЛКМ, чтобы открыть ссылку"
    page._cell_entered(0, 1)
    assert page.table.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    page._cell_entered(0, DATA_COLUMN)
    page.eventFilter(page.table.viewport(), QEvent(QEvent.Type.Leave))
    assert page.table.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    app.processEvents()


def test_issued_sheet_shows_flag_and_is_read_only(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import TablePage, _status_color

    page = TablePage()
    page.set_data(
        object_name="Объект",
        catalog={"columns": [{"key": "s1", "label": "1"}], "parameters": []},
        workbook={"id": "issued", "is_primary": False, "is_issued": True, "cells": []},
        unsaved=[],
        sheets=[
            {"id": "primary", "name": "Исходные данные", "is_primary": True, "is_issued": False},
            {"id": "issued", "name": "01.04.2026", "is_primary": False, "is_issued": True},
        ],
        can_write=True,
        busy=False,
    )
    assert page.edit_btn.isHidden()
    assert page.sheet_bar.buttons["issued"].icon().isNull() is False
    assert page.sheet_bar.buttons["primary"].icon().isNull()
    assert "только для просмотра" in page.mode_hint.text()
    assert _status_color({"status": "confirmed"}, "editable", show_changes=False) is None
    app.processEvents()


def test_parameter_names_fit_on_one_line(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import TablePage

    long_name = "Угол установки профиля в корневом сечении (α'уст)"
    page = TablePage()
    page.set_data(
        object_name="Объект",
        catalog={
            "columns": [{"key": "s1", "label": "1"}],
            "parameters": [
                {"key": "r005", "label": "Сопловая лопатка:", "row_kind": "section", "indent": 0},
                {"key": "r007", "label": long_name, "row_kind": "editable", "indent": 1, "unit": "°"},
                {"key": "r010", "label": "Высота сопловой лопатки (L'), мм", "row_kind": "editable", "indent": 1, "unit": "мм"},
            ],
        },
        workbook={"id": "sheet", "is_primary": True, "is_issued": False, "cells": [], "sheet_name": "Исходные данные"},
        unsaved=[],
        sheets=[{"id": "sheet", "name": "Исходные данные", "is_primary": True}],
        can_write=True,
        busy=False,
    )
    assert page.table.item(0, 0).text() == ""
    assert page.table.item(1, 0).text() == "1"
    assert page.table.item(2, 0).text() == "2"
    name = page.table.item(1, 1).text()
    assert "\n" not in name
    assert "α'уст" not in name
    assert "Угол установки профиля в корневом сечении" in name
    assert page.table.wordWrap() is False
    assert page.table.frozen.wordWrap() is False
    assert page.table.columnWidth(1) >= QFontMetrics(page.table.font()).horizontalAdvance(name)
    assert page.table.frozen.columnWidth(1) == page.table.columnWidth(1)
    assert page.table.horizontalHeaderItem(0).text() == "№"
    assert page.table.horizontalHeaderItem(2).text() == "Обозначение"
    assert page.table.horizontalHeaderItem(3).text() == "Ед. изм."
    assert page.table.item(1, 2).text() == "α'уст"
    assert page.table.item(1, 3).text() == "°"
    assert "\n" not in page.table.item(1, 2).text()
    longer = "Ширина профиля в рабочем положении (корневое сечение)"
    page.set_data(
        object_name="Объект",
        catalog={
            "columns": [{"key": "s1", "label": "1"}],
            "parameters": [
                {"key": "r004", "excel_row": 4, "label": "Характеристики проточной части:", "row_kind": "section", "indent": 0},
                {"key": "r005", "excel_row": 5, "label": "Сопловая лопатка:", "row_kind": "section", "indent": 0},
                {"key": "r006", "excel_row": 6, "label": "Чертеж теоретического профиля (Профиль)", "row_kind": "editable", "indent": 1},
                {"key": "r007", "excel_row": 7, "label": long_name, "row_kind": "editable", "indent": 1, "unit": "°"},
                {"key": "r012", "excel_row": 12, "label": longer + " (B'к), мм", "row_kind": "editable", "indent": 1, "unit": "мм"},
            ],
        },
        workbook={"id": "sheet", "is_primary": True, "is_issued": False, "cells": [], "sheet_name": "Исходные данные"},
        unsaved=[],
        sheets=[{"id": "sheet", "name": "Исходные данные", "is_primary": True}],
        can_write=True,
        busy=False,
    )
    reference = page.table.item(3, 1).text()
    assert "Угол установки профиля в корневом сечении" in reference
    fitted = QFontMetrics(page.table.font()).horizontalAdvance(reference) + 28
    assert page.table.columnWidth(1) >= fitted
    assert page.table.columnWidth(1) < QFontMetrics(page.table.font()).horizontalAdvance(page.table.item(4, 1).text())
    plain = {
        "key": "r004",
        "label": "Базовая конструкция (турбина, ступень)",
        "row_kind": "section",
        "indent": 0,
    }
    from desktop.ui.table_page import parameter_designation, parameter_display_label

    assert parameter_designation(plain) == ""
    kept = {
        "key": "r012",
        "label": "Ширина профиля в рабочем положении (корневое сечение) (B'к), мм",
        "unit": "мм",
    }
    assert parameter_display_label(kept) == "Ширина профиля в рабочем положении (корневое сечение)"
    assert parameter_designation(kept) == "B'к"
    page.set_history(
        [
            {"created_at": "2026-04-01T00:00:02+00:00", "author": "user", "old_value": "130", "new_value": "140", "comment": "Изменение листа «01.04.2026»"},
            {"created_at": "2026-03-01T00:00:00+00:00", "author": "user", "old_value": None, "new_value": "120", "comment": "Данные из основного листа"},
            {"created_at": "2026-03-15T00:00:01+00:00", "author": "user", "old_value": "120", "new_value": "130", "comment": "Изменение листа «15.03.2026»"},
        ]
    )
    assert page.history_table.item(0, 4).text() == "Данные из основного листа"
    assert page.history_table.item(1, 4).text() == "Изменение листа «15.03.2026»"
    assert page.history_table.item(2, 4).text() == "Изменение листа «01.04.2026»"


def test_id_table_units_use_superscript(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import UNIT_ROLE, TablePage, format_unit

    assert format_unit("мм2") == "мм²"
    assert format_unit("мм3") == "мм³"
    assert format_unit("кг/см2") == "кг/см²"
    assert format_unit("м-1") == "м⁻¹"
    assert format_unit("мм^2") == "мм²"
    assert format_unit("мм") == "мм"
    assert format_unit("°") == "°"
    assert format_unit("Площадь, мм2") == "Площадь, мм²"
    assert format_unit("12Х13") == "12Х13"
    assert format_unit("15Х1М1Ф") == "15Х1М1Ф"
    assert format_unit("2170ТЧ") == "2170ТЧ"
    assert format_unit("К-230-12,8") == "К-230-12,8"
    page = TablePage()
    page.set_data(
        object_name="Объект",
        catalog={
            "columns": [{"key": "s1", "label": "1", "kind": "stage"}],
            "parameters": [
                {"key": "r009", "label": "Теоретическая выходная площадь (Fc,), мм2", "row_kind": "editable", "unit": "мм2"},
                {"key": "r010", "label": "Высота сопловой лопатки, мм", "row_kind": "editable", "unit": "мм"},
            ],
        },
        workbook={"id": "sheet", "is_primary": True, "is_issued": False, "cells": [], "sheet_name": "Исходные данные"},
        unsaved=[],
        sheets=[{"id": "sheet", "name": "Исходные данные", "is_primary": True}],
        can_write=True,
        busy=False,
    )
    assert page.table.item(0, 3).text() == "мм²"
    assert page.table.item(0, 3).data(UNIT_ROLE) == "мм2"
    assert page.table.frozen.item(0, 3).text() == "мм²"
    assert page.table.item(1, 3).text() == "мм"
    page._select_keys("r009", "s1", emit=False)
    assert "мм²" in page.cell_caption.text()


def test_stage_columns_follow_row_15(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.table_page import DATA_COLUMN, TablePage

    page = TablePage()
    long_value = "Чертеж теоретического профиля очень длинный"
    page.set_data(
        object_name="Объект",
        catalog={
            "columns": [
                {"key": "s1", "label": "1", "kind": "stage"},
                {"key": "s2", "label": "2", "kind": "stage"},
                {"key": "pku1", "label": "ПКУ", "kind": "pku"},
            ],
            "parameters": [
                {"key": f"r{index:03d}", "excel_row": index, "label": f"Параметр {index}", "row_kind": "editable"}
                for index in range(4, 16)
            ],
        },
        workbook={
            "id": "sheet",
            "is_primary": True,
            "is_issued": False,
            "sheet_name": "Исходные данные",
            "cells": [
                {"parameter_key": "r015", "column_key": "s1", "display": "Единичные НЛ"},
                {"parameter_key": "r015", "column_key": "s2", "display": "12"},
                {"parameter_key": "r006", "column_key": "s1", "display": long_value},
            ],
        },
        unsaved=[],
        sheets=[{"id": "sheet", "name": "Исходные данные", "is_primary": True}],
        can_write=True,
        busy=False,
    )
    metrics = QFontMetrics(page.table.font())
    fitted = metrics.horizontalAdvance("Единичные НЛ") + 20
    assert page.table.columnWidth(DATA_COLUMN) >= fitted
    assert page.table.columnWidth(DATA_COLUMN + 1) == page.table.columnWidth(DATA_COLUMN)
    assert page.table.columnWidth(DATA_COLUMN) < metrics.horizontalAdvance(long_value)
    assert page.table.columnWidth(DATA_COLUMN + 2) < page.table.columnWidth(DATA_COLUMN)


def test_id_table_header_uses_the_same_horizontal_scroll_as_the_body():
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QTableWidgetItem

    app = QApplication.instance() or QApplication([])
    from desktop.ui.sheet_table import FrozenSheetTable
    from desktop.ui.style import APP_QSS

    table = FrozenSheetTable()
    table.setStyleSheet(APP_QSS)
    table.setColumnCount(12)
    table.setRowCount(4)
    for column in range(12):
        table.setHorizontalHeaderItem(column, QTableWidgetItem(str(column)))
        table.setColumnWidth(column, 160)
    table.resize(420, 220)
    table.show()
    app.processEvents()
    table.sync_frozen()
    bar = table.horizontalScrollBar()
    bar.setValue(min(120, bar.maximum()))
    app.processEvents()
    assert bar.value() > 0
    assert table.horizontalHeader().offset() == bar.value()
    assert table.horizontalHeader().horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert not table.horizontalHeader().horizontalScrollBar().isVisible()
    assert table.frozen.horizontalHeader().horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert not table.frozen.horizontalHeader().horizontalScrollBar().isVisible()
    assert not table.frozen.horizontalHeader().isVisible()
    table.horizontalHeader().resizeSection(1, 280)
    app.processEvents()
    assert table.columnWidth(1) == 280
    assert table.horizontalHeader().sectionSize(1) == 280
    assert table.frozen.columnWidth(1) == 280
    table.close()
    app.processEvents()


def test_report_selects_groups_blocks_rows_and_column_groups():
    import json
    from pathlib import Path

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.report_page import ReportPage, section_descendants

    catalog_path = Path(__file__).parents[1] / "templates" / "parameter_catalog.json"
    real = json.loads(catalog_path.read_text(encoding="utf-8"))
    tree = section_descendants(real["parameters"])
    assert "r006" in tree["r004"]
    assert "r018" in tree["r004"]
    assert "r006" in tree["r005"]
    assert "r018" not in tree["r005"]
    assert set(tree["r034"]).issubset(set(tree["r017"]))
    assert "r006" not in tree["r017"]

    page = ReportPage()
    catalog = {
        "columns": [
            {"key": "s1", "label": "1", "kind": "stage"},
            {"key": "s2", "label": "2", "kind": "stage"},
            {"key": "pku1", "label": "1 ПКУ", "kind": "pku"},
        ],
        "parameters": [
            {"key": "chapter", "label": "Характеристики проточной части:", "row_kind": "section", "indent": 0},
            {"key": "nozzle", "label": "Сопловая лопатка:", "row_kind": "section", "indent": 0},
            {"key": "r1", "label": "Высота", "row_kind": "editable", "indent": 1, "group": "nozzle"},
            {"key": "r2", "label": "Угол", "row_kind": "editable", "indent": 1, "group": "nozzle"},
            {"key": "diaphragm", "label": "Диафрагма:", "row_kind": "section", "indent": 0},
            {"key": "nested", "label": "Тип ДУ:", "row_kind": "section", "indent": 1},
            {"key": "r3", "label": "Толщина", "row_kind": "editable", "indent": 2, "group": "nested"},
        ],
    }
    page.set_table_data(catalog, [], sheet_id="sheet")
    assert page.table.cellWidget(0, 0) is None
    assert page.table.cellWidget(1, 0) is not None
    page._toggle_table()
    assert page._included_params == {"r1", "r2", "r3"}
    page._toggle_table()
    assert page._included_params == set()
    page._toggle_section("nozzle")
    assert page._included_params == {"r1", "r2"}
    page._toggle_parameter("r1")
    assert page._included_params == {"r2"}
    assert page.table.cellWidget(1, 0).text() == "±"
    page._toggle_section("chapter")
    assert page._included_params == {"r1", "r2", "r3"}
    assert [item["key"] for item in page._preview_parameters()] == [
        "chapter",
        "nozzle",
        "r1",
        "r2",
        "diaphragm",
        "nested",
        "r3",
    ]
    page._toggle_section("nested")
    assert page._included_params == {"r1", "r2"}
    page._toggle_header_group(3)
    assert page._included_cols == {"s1", "s2"}
    page._toggle_column("s1")
    assert page._included_cols == {"s2"}
    page._toggle_header_group(5)
    assert page._included_cols == {"s2", "pku1"}
    page.close()
    app.processEvents()


def test_custom_report_starts_selected_and_marks_saved_changes():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from desktop.ui.report_page import ReportPage

    page = ReportPage()
    assert page.current_type() == "custom"
    assert page.type_combo.currentText() == "Кастомный отчет"
    catalog = {
        "columns": [
            {"key": "s1", "label": "1", "kind": "stage"},
            {"key": "s2", "label": "2", "kind": "stage"},
            {"key": "pku1", "label": "1 ПКУ", "kind": "pku"},
        ],
        "parameters": [
            {"key": "nozzle", "label": "Сопловая лопатка:", "row_kind": "section", "indent": 0},
            {"key": "r010", "label": "Высота", "row_kind": "editable", "indent": 1},
            {"key": "r011", "label": "Парциальность", "row_kind": "editable", "indent": 1},
            {"key": "r047", "label": "Высота рабочих", "row_kind": "editable", "indent": 1},
        ],
    }
    page.set_table_data(
        catalog,
        [
            {"parameter_key": "r010", "column_key": "s1", "status": "confirmed", "value": "46"},
            {"parameter_key": "r011", "column_key": "s2", "status": "draft", "value": "1"},
            {"parameter_key": "r047", "column_key": "pku1", "status": "initial", "excel_highlight": True, "value": "20"},
        ],
        sheet_id="sheet",
    )
    assert page._included_params == {"r010", "r047"}
    assert page._included_cols == {"s1", "pku1"}
    page.type_combo.setCurrentIndex(page.type_combo.findData("short"))
    assert page.current_type() == "short"
    assert page._included_params == {"r010", "r047"}
    assert page._included_cols == {"s1", "s2", "pku1"}
    page.type_combo.setCurrentIndex(page.type_combo.findData("full"))
    assert page._included_params == {"r010", "r011", "r047"}
    assert page._included_cols == {"s1", "s2", "pku1"}
    page.use_custom_report()
    assert page.current_type() == "custom"
    assert page._included_params == {"r010", "r047"}
    assert page._included_cols == {"s1", "pku1"}
    from desktop.ui.report_page import _status_brush

    assert _status_brush({"status": "initial", "excel_highlight": True}, "editable") is None
    page.close()
    app.processEvents()


def test_report_preview_opens_fullscreen_like_the_web_sheet():
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QLabel, QTableWidget

    app = QApplication.instance() or QApplication([])
    from desktop.ui.report_page import PreviewHeader, ReportPage
    from desktop.ui.style import SECTION_BG

    page = ReportPage()
    page.set_table_data(
        {
            "columns": [
                {"key": "s1", "label": "1", "kind": "stage"},
                {"key": "s2", "label": "2", "kind": "stage"},
            ],
            "parameters": [
                {"key": "nozzle", "label": "Сопловая лопатка:", "row_kind": "section", "indent": 0},
                {"key": "r1", "label": "Высота сопловой лопатки", "row_kind": "editable", "indent": 1, "unit": "мм"},
            ],
        },
        [{"parameter_key": "r1", "column_key": "s1", "display": "120", "status": "confirmed"}],
        sheet_id="sheet",
    )
    page._included_params = {"r1"}
    page._included_cols = {"s1", "s2"}
    dialog = page._build_preview()
    assert dialog is not None
    dialog.show()
    app.processEvents()
    screen = dialog.screen() or app.primaryScreen()
    assert screen is not None
    assert dialog.geometry().size() == screen.geometry().size()
    assert dialog.windowState() & Qt.WindowState.WindowFullScreen
    title = dialog.findChild(QLabel, "report-preview-title")
    assert title is not None and title.text() == "Предпросмотр таблицы"
    assert dialog.grab().toImage().pixelColor(12, 8).name() == "#1f5e93"
    table = dialog.findChild(QTableWidget, "report-preview-grid")
    assert isinstance(table.horizontalHeader(), PreviewHeader)
    assert table.columnWidth(0) == 340
    assert table.columnWidth(1) == 80
    assert [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())] == [
        "Наименование параметра",
        "Ед. изм.",
        "1",
        "2",
    ]
    assert table.item(0, 0).text() == "Сопловая лопатка:"
    assert table.item(0, 0).font().bold()
    assert table.item(0, 0).background().color().name() == SECTION_BG
    assert table.item(1, 0).data(Qt.ItemDataRole.UserRole) == 1
    assert table.item(1, 1).text() == "мм"
    assert table.item(1, 2).text() == "120"
    assert table.item(1, 2).background().color().name() == "#c8e6c9"
    dialog.close()
    page.close()
    app.processEvents()
