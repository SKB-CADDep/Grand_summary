from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.style import COMPUTED, CONFIRMED, DRAFT, HEADER_BG, PARAM_BG, SECTION_BG, UNIFIED
from src.services.report_generation import SHORT_NOZZLE_ROWS, SHORT_ROTOR_ROWS

HEADER_LINE = QColor("#d9e3f0")
HEADER_TEXT = QColor("#263238")
INCLUDED_BG = QColor("#62d987")
INCLUDED_BD = QColor("#27934a")
INCLUDED_FG = QColor("#174d2b")
EXCLUDED_BG = QColor("#f3f5f8")
EXCLUDED_BD = QColor("#dfe4eb")
EXCLUDED_FG = QColor("#748094")
DIM = QColor("#9aa5b4")


_COLUMN_GROUP_TITLES = {
    "stage": "Ступени",
    "pku": "ПКУ",
    "zku": "ЗКУ",
}
_SHORT_PARAMETER_KEYS = {key for key, _label in (*SHORT_NOZZLE_ROWS, *SHORT_ROTOR_ROWS)} | {"r098", "r099", "r100"}


def _saved_change(cell: dict) -> bool:
    if (cell.get("status") or "") == "draft":
        return False
    if cell.get("excel_highlight"):
        return True
    return (cell.get("status") or "") in {"confirmed", "triangle"}


def section_descendants(parameters: list[dict]) -> dict[str, list[str]]:
    sections = [index for index, param in enumerate(parameters) if param.get("row_kind") == "section"]
    ends: dict[int, int] = {}
    for position, index in enumerate(sections):
        indent = int(parameters[index].get("indent") or 0)
        end = len(parameters)
        for next_index in sections[position + 1 :]:
            if int(parameters[next_index].get("indent") or 0) <= indent:
                end = next_index
                break
        ends[index] = end
    for index in sections:
        indent = int(parameters[index].get("indent") or 0)
        if any(parameters[row].get("row_kind") != "section" for row in range(index + 1, ends[index])):
            continue
        cursor = ends[index]
        while cursor < len(parameters) and parameters[cursor].get("row_kind") == "section":
            if int(parameters[cursor].get("indent") or 0) != indent:
                break
            next_end = ends[cursor]
            if not any(parameters[row].get("row_kind") != "section" for row in range(cursor + 1, next_end)):
                break
            ends[index] = next_end
            cursor = next_end
    return {
        parameters[index]["key"]: [
            parameters[row]["key"]
            for row in range(index + 1, ends[index])
            if parameters[row].get("row_kind") != "section"
        ]
        for index in sections
    }


def column_groups(columns: list[dict]) -> list[dict]:
    groups: list[dict] = []
    for offset, column in enumerate(columns):
        kind = column.get("kind") or "other"
        if not groups or groups[-1]["kind"] != kind:
            groups.append(
                {
                    "kind": kind,
                    "title": _COLUMN_GROUP_TITLES.get(kind, "Столбцы"),
                    "start": offset,
                    "keys": [],
                }
            )
        groups[-1]["keys"].append(column.get("key"))
    return groups


def inclusion_state(keys: list[str], included: set[str]) -> str:
    if not keys:
        return "none"
    selected = sum(1 for key in keys if key in included)
    if selected == 0:
        return "none"
    if selected == len(keys):
        return "all"
    return "partial"


def _param_label(param: dict) -> str:
    label = param.get("label") or ""
    unit = param.get("unit") or ""
    if unit and label.endswith(f", {unit}"):
        return label[: -len(unit) - 2].strip()
    return label


def _status_brush(cell: dict | None, row_kind: str) -> QBrush | None:
    if row_kind != "editable":
        return QBrush(QColor(COMPUTED))
    if not cell:
        return None
    if cell.get("locked"):
        return QBrush(QColor(COMPUTED))
    if cell.get("unified"):
        return QBrush(QColor(UNIFIED))
    status = cell.get("status") or "empty"
    if status == "draft":
        return QBrush(QColor(DRAFT))
    if status == "confirmed":
        return QBrush(QColor(CONFIRMED))
    if status == "computed":
        return QBrush(QColor(COMPUTED))
    return None


class PreviewHeader(QHeaderView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHighlightSections(False)

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        hint.setHeight(max(44, hint.height() * 2))
        return hint

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:  # noqa: N802
        painter.save()
        painter.fillRect(rect, QColor(HEADER_BG))
        painter.setPen(HEADER_LINE)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(HEADER_TEXT)
        model = self.model()
        text = str(model.headerData(logicalIndex, self.orientation()) or "") if model else ""
        if logicalIndex == 0:
            painter.drawText(
                rect.adjusted(8, 2, -8, -2),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )
        elif logicalIndex == 1:
            painter.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignCenter, text)
        else:
            bottom = QRect(rect.left(), rect.top() + rect.height() // 2, rect.width(), rect.height() - rect.height() // 2)
            painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() <= 2:
            return
        first = self.sectionViewportPosition(2)
        last_index = self.count() - 1
        last = self.sectionViewportPosition(last_index) + self.sectionSize(last_index)
        top = QRect(first, 0, max(0, last - first), self.height() // 2)
        painter = QPainter(self.viewport())
        painter.fillRect(top, QColor("#f3f7fc"))
        painter.setPen(HEADER_LINE)
        painter.drawRect(top.adjusted(0, 0, -1, -1))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(HEADER_TEXT)
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, "Ступени")


class _PreviewNameDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        indent = int(index.data(Qt.ItemDataRole.UserRole) or 0)
        option.rect = option.rect.adjusted(6 + max(0, indent) * 14, 2, -6, -2)
        super().paint(painter, option, index)


class _ReportPreviewDialog(QDialog):
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.property("_filling_screen"):
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        self.setProperty("_filling_screen", True)
        self.setGeometry(screen.geometry())
        self.setWindowState(self.windowState() | Qt.WindowState.WindowFullScreen)
        self.setProperty("_filling_screen", False)


class ReportHeader(QHeaderView):
    column_toggle_requested = pyqtSignal(int)
    column_group_toggle_requested = pyqtSignal(int)
    table_toggle_requested = pyqtSignal()

    def __init__(self, table: "ReportPage") -> None:
        super().__init__(Qt.Orientation.Horizontal, table.table if hasattr(table, "table") else None)
        self._page = table
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHighlightSections(False)
        self.setSectionsClickable(True)

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        hint.setHeight(max(66, hint.height() * 3))
        return hint

    def _toggle_band(self, rect: QRect) -> QRect:
        third = rect.height() // 3
        return QRect(rect.left(), rect.top() + third, rect.width(), third)

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:  # noqa: N802
        painter.save()
        painter.fillRect(rect, QColor(HEADER_BG))
        painter.setPen(HEADER_LINE)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(HEADER_TEXT)
        model = self.model()
        text = str(model.headerData(logicalIndex, self.orientation()) or "") if model else ""
        if logicalIndex == 0:
            band_height = rect.height() // 3
            mark = QRect(rect.center().x() - 11, max(2, band_height // 2 - 11), 22, 22)
            self._paint_mark(painter, mark, self._rows_state())
            painter.restore()
            return
        if logicalIndex < 3:
            painter.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
            painter.restore()
            return
        bottom = QRect(rect.left(), rect.top() + 2 * rect.height() // 3, rect.width(), rect.height() // 3)
        painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, text)
        band = self._toggle_band(rect)
        columns = (self._page._catalog or {}).get("columns") or []
        key = columns[logicalIndex - 3].get("key") if logicalIndex - 3 < len(columns) else None
        included = bool(key and key in self._page._included_cols)
        mark = QRect(band.center().x() - 11, band.center().y() - 11, 22, 22)
        painter.setBrush(QBrush(INCLUDED_BG if included else EXCLUDED_BG))
        painter.setPen(INCLUDED_BD if included else EXCLUDED_BD)
        painter.drawRoundedRect(mark, 6, 6)
        painter.setPen(INCLUDED_FG if included else EXCLUDED_FG)
        painter.drawText(mark, Qt.AlignmentFlag.AlignCenter, "+" if included else "−")
        painter.restore()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        groups = column_groups((self._page._catalog or {}).get("columns") or [])
        if not groups:
            return
        painter = QPainter(self.viewport())
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        band_height = self.height() // 3
        for group in groups:
            start = 3 + group["start"]
            end = start + len(group["keys"]) - 1
            if end >= self.count():
                continue
            left = self.sectionViewportPosition(start)
            right = self.sectionViewportPosition(end) + self.sectionSize(end)
            top = QRect(left, 0, max(0, right - left), band_height)
            painter.fillRect(top, QColor(HEADER_BG))
            painter.setPen(HEADER_LINE)
            painter.drawRect(top.adjusted(0, 0, -1, -1))
            state = inclusion_state(group["keys"], self._page._included_cols)
            mark = QRect(top.left() + 4, top.center().y() - 11, 22, 22)
            self._paint_mark(painter, mark, state)
            painter.setPen(HEADER_TEXT)
            painter.drawText(top.adjusted(30, 0, -4, 0), Qt.AlignmentFlag.AlignCenter, group["title"])

    def _rows_state(self) -> str:
        keys = [
            item.get("key") or ""
            for item in (self._page._catalog or {}).get("parameters") or []
            if item.get("row_kind") != "section" and item.get("key")
        ]
        return inclusion_state(keys, self._page._included_params)

    def _paint_mark(self, painter: QPainter, mark: QRect, state: str) -> None:
        included = state == "all"
        painter.setBrush(QBrush(INCLUDED_BG if included else EXCLUDED_BG))
        painter.setPen(INCLUDED_BD if included else EXCLUDED_BD)
        painter.drawRoundedRect(mark, 6, 6)
        painter.setPen(INCLUDED_FG if included else EXCLUDED_FG)
        painter.drawText(mark, Qt.AlignmentFlag.AlignCenter, "+" if included else ("±" if state == "partial" else "−"))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        index = self.logicalIndexAt(pos)
        if index == 0 and pos.y() < self.height() // 3:
            self.table_toggle_requested.emit()
            return
        if index >= 3:
            section_x = self.sectionViewportPosition(index)
            rect = QRect(section_x, 0, self.sectionSize(index), self.height())
            third = rect.height() // 3
            if pos.y() < third:
                self.column_group_toggle_requested.emit(index)
                return
            if self._toggle_band(rect).contains(QPoint(pos.x(), pos.y())):
                self.column_toggle_requested.emit(index)
                return
        super().mousePressEvent(event)


class ReportPage(QWidget):
    preview_requested = pyqtSignal(str, str)
    export_requested = pyqtSignal(str, list, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheets: list[dict] = []
        self._catalog: dict | None = None
        self._cells: dict[str, dict] = {}
        self._included_params: set[str] = set()
        self._included_cols: set[str] = set()
        self._section_descendants: dict[str, list[str]] = {}
        self._sheet_id = ""
        self._busy = False
        self._reselect = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        type_box = QVBoxLayout()
        type_label = QLabel("Тип записки")
        type_label.setProperty("role", "hint")
        type_box.addWidget(type_label)
        self.type_combo = QComboBox()
        self.type_combo.addItem("Кастомный отчет", "custom")
        self.type_combo.addItem("Исходные данные по проточной части", "short")
        self.type_combo.addItem("Исходные данные по облопачиванию", "full")
        self.type_combo.setMinimumWidth(280)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        type_box.addWidget(self.type_combo)
        toolbar.addLayout(type_box)
        sheet_box = QVBoxLayout()
        sheet_label = QLabel("Лист таблицы ИД")
        sheet_label.setProperty("role", "hint")
        sheet_box.addWidget(sheet_label)
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(220)
        self.sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        sheet_box.addWidget(self.sheet_combo)
        toolbar.addLayout(sheet_box)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setObjectName("report-sheet")
        header = ReportHeader(self)
        self.table.setHorizontalHeader(header)
        header.column_toggle_requested.connect(self._toggle_header_column)
        header.column_group_toggle_requested.connect(self._toggle_header_group)
        header.table_toggle_requested.connect(self._toggle_table)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.preview_btn = QPushButton("Предпросмотр")
        self.export_btn = QPushButton("Экспорт в Word")
        self.preview_btn.clicked.connect(self._preview)
        self.export_btn.clicked.connect(self._export)
        buttons.addWidget(self.preview_btn)
        buttons.addWidget(self.export_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.empty = QLabel("Сначала выберите объект и откройте таблицу ИД.")
        self.empty.setProperty("role", "hint")
        root.addWidget(self.empty)

    def set_sheets(self, sheets: list[dict], preferred_id: str | None = None) -> None:
        self._sheets = sheets
        self.sheet_combo.blockSignals(True)
        current = preferred_id or self.sheet_combo.currentData()
        self.sheet_combo.clear()
        for sheet in sheets:
            self.sheet_combo.addItem(sheet.get("name") or "", sheet.get("id"))
        if current:
            index = self.sheet_combo.findData(current)
            if index >= 0:
                self.sheet_combo.setCurrentIndex(index)
        self.sheet_combo.blockSignals(False)

    def set_table_data(
        self,
        catalog: dict | None,
        cells: list[dict],
        busy: bool = False,
        sheet_id: str | None = None,
    ) -> None:
        self._busy = busy
        next_id = str(sheet_id or self.current_sheet_id() or "")
        sheet_changed = next_id != self._sheet_id
        self._sheet_id = next_id
        self._catalog = catalog
        self._cells = {f"{cell.get('parameter_key')}:{cell.get('column_key')}": cell for cell in cells}
        if catalog and (sheet_changed or self._reselect):
            self._apply_type_selection()
            self._reselect = False
        self._rebuild()
        self._refresh_actions()
        self.empty.setVisible(catalog is None)

    def current_sheet_id(self) -> str:
        return str(self.sheet_combo.currentData() or "")

    def current_type(self) -> str:
        return str(self.type_combo.currentData() or "custom")

    def use_custom_report(self) -> None:
        self.type_combo.blockSignals(True)
        index = self.type_combo.findData("custom")
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.type_combo.blockSignals(False)
        self._reselect = True
        if self._catalog is not None:
            self._apply_type_selection()
            self._reselect = False
            self._rebuild()
            self._refresh_actions()

    def _type_changed(self) -> None:
        if self._catalog is None:
            return
        self._apply_type_selection()
        self._rebuild()
        self._refresh_actions()

    def _apply_type_selection(self) -> None:
        catalog = self._catalog or {}
        parameters = [item for item in catalog.get("parameters") or [] if item.get("row_kind") != "section" and item.get("key")]
        columns = [item for item in catalog.get("columns") or [] if item.get("key")]
        kind = self.current_type()
        if kind == "full":
            self._included_params = {item["key"] for item in parameters}
            self._included_cols = {item["key"] for item in columns}
            return
        if kind == "short":
            self._included_params = {item["key"] for item in parameters if item["key"] in _SHORT_PARAMETER_KEYS}
            self._included_cols = {item["key"] for item in columns if item.get("kind") in {"stage", "pku", "zku"}}
            return
        param_keys = {item["key"] for item in parameters}
        col_keys = {item["key"] for item in columns}
        saved = [cell for cell in self._cells.values() if _saved_change(cell)]
        self._included_params = {cell.get("parameter_key") for cell in saved if cell.get("parameter_key") in param_keys}
        self._included_cols = {cell.get("column_key") for cell in saved if cell.get("column_key") in col_keys}

    def _sheet_changed(self) -> None:
        sheet_id = self.current_sheet_id()
        if sheet_id:
            self.preview_requested.emit(sheet_id, self.current_type())

    def _refresh_actions(self) -> None:
        ready = bool(self._included_params and self._included_cols and self._catalog)
        self.preview_btn.setDisabled(not ready)
        self.export_btn.setDisabled(self._busy or not ready)

    def _toggle_button(self, included: bool, tooltip: str, handler, partial: bool = False) -> QPushButton:
        button = QPushButton("+" if included else ("±" if partial else "−"))
        button.setProperty("included", "true" if included else "false")
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        button.style().unpolish(button)
        button.style().polish(button)
        return button

    def _rebuild(self) -> None:
        catalog = self._catalog
        scroll_x = self.table.horizontalScrollBar().value()
        scroll_y = self.table.verticalScrollBar().value()
        self.table.clear()
        if not catalog:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        columns = catalog.get("columns") or []
        parameters = catalog.get("parameters") or []
        self._section_descendants = section_descendants(parameters)
        self.table.setColumnCount(3 + len(columns))
        self.table.setHorizontalHeaderLabels([" ", "Наименование параметра", "Ед. изм."] + [col.get("label") or "" for col in columns])
        self.table.setRowCount(len(parameters))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 36)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 320)
        header.resizeSection(2, 80)
        self.table.verticalHeader().setDefaultSectionSize(24)
        for row, param in enumerate(parameters):
            section = param.get("row_kind") == "section"
            key = param.get("key") or ""
            label = _param_label(param)
            if section:
                descendants = self._section_descendants.get(key, [])
                state = inclusion_state(descendants, self._included_params)
                covers_table = bool(descendants) and set(descendants) == set(self._all_parameter_keys())
                if descendants and not covers_table:
                    button = self._toggle_button(
                        state == "all",
                        f"{'Убрать из отчёта группу' if state == 'all' else 'Добавить в отчёт группу'}: {label}",
                        lambda _=False, section_key=key: self._toggle_section(section_key),
                        partial=state == "partial",
                    )
                    self.table.setCellWidget(row, 0, button)
            else:
                included = key in self._included_params
                button = self._toggle_button(
                    included,
                    f"{'Убрать из отчёта' if included else 'Добавить в отчёт'}: {label}",
                    lambda _=False, param_key=key: self._toggle_parameter(param_key),
                )
                self.table.setCellWidget(row, 0, button)
            name = QTableWidgetItem(("    " * int(param.get("indent") or 0)) + _param_label(param))
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setBackground(QBrush(QColor(SECTION_BG if section else PARAM_BG)))
            if section:
                font = name.font()
                font.setBold(True)
                name.setFont(font)
            self.table.setItem(row, 1, name)
            unit_item = QTableWidgetItem(param.get("unit") or "" if param.get("row_kind") == "editable" else "")
            unit_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            unit_item.setBackground(QBrush(QColor(SECTION_BG if section else PARAM_BG)))
            self.table.setItem(row, 2, unit_item)
            if section:
                dim_row = inclusion_state(self._section_descendants.get(key, []), self._included_params) == "none"
            else:
                dim_row = key not in self._included_params
            for col_index, column in enumerate(columns):
                cell = self._cells.get(f"{param.get('key')}:{column.get('key')}")
                item = QTableWidgetItem((cell or {}).get("display") or "")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                brush = _status_brush(cell, param.get("row_kind") or "editable")
                if brush:
                    item.setBackground(brush)
                dim_col = column.get("key") not in self._included_cols
                if dim_row or dim_col:
                    item.setForeground(QBrush(DIM))
                self.table.setItem(row, 3 + col_index, item)
            if dim_row:
                name.setForeground(QBrush(DIM))
                unit_item.setForeground(QBrush(DIM))
        self.table.horizontalScrollBar().setValue(scroll_x)
        self.table.verticalScrollBar().setValue(scroll_y)
        header.update()
        header.viewport().update()

    def _toggle_keys(self, keys: list[str], included: set[str]) -> None:
        if keys and all(key in included for key in keys):
            included.difference_update(keys)
        else:
            included.update(keys)

    def _all_parameter_keys(self) -> list[str]:
        return [
            item["key"]
            for item in (self._catalog or {}).get("parameters") or []
            if item.get("row_kind") != "section" and item.get("key")
        ]

    def _toggle_table(self) -> None:
        self._toggle_keys(self._all_parameter_keys(), self._included_params)
        self._rebuild()
        self._refresh_actions()

    def _toggle_section(self, key: str) -> None:
        self._toggle_keys(self._section_descendants.get(key, []), self._included_params)
        self._rebuild()
        self._refresh_actions()

    def _toggle_parameter(self, key: str) -> None:
        if key in self._included_params:
            self._included_params.discard(key)
        else:
            self._included_params.add(key)
        self._rebuild()
        self._refresh_actions()

    def _toggle_header_column(self, logical_index: int) -> None:
        columns = (self._catalog or {}).get("columns") or []
        index = logical_index - 3
        if 0 <= index < len(columns):
            self._toggle_column(columns[index]["key"])

    def _toggle_header_group(self, logical_index: int) -> None:
        columns = (self._catalog or {}).get("columns") or []
        index = logical_index - 3
        for group in column_groups(columns):
            if group["start"] <= index < group["start"] + len(group["keys"]):
                self._toggle_keys([key for key in group["keys"] if key], self._included_cols)
                self._rebuild()
                self._refresh_actions()
                return

    def _toggle_column(self, key: str) -> None:
        if key in self._included_cols:
            self._included_cols.discard(key)
        else:
            self._included_cols.add(key)
        self._rebuild()
        self._refresh_actions()

    def _selected_keys(self) -> tuple[list[str], list[str]]:
        catalog = self._catalog or {}
        params = [item["key"] for item in catalog.get("parameters") or [] if item["key"] in self._included_params]
        cols = [item["key"] for item in catalog.get("columns") or [] if item["key"] in self._included_cols]
        return params, cols

    def _preview_parameters(self) -> list[dict]:
        parameters = (self._catalog or {}).get("parameters") or []
        visible_sections = {
            key
            for key, descendants in self._section_descendants.items()
            if any(item in self._included_params for item in descendants)
        }
        return [
            item
            for item in parameters
            if item.get("key") in self._included_params
            or (item.get("row_kind") == "section" and item.get("key") in visible_sections)
        ]

    def _build_preview(self) -> QDialog | None:
        params, cols = self._selected_keys()
        if not params or not cols:
            return None
        dialog = _ReportPreviewDialog(self.window() or self)
        dialog.setObjectName("report-preview")
        dialog.setWindowTitle("Предпросмотр таблицы")
        dialog.setModal(True)
        dialog.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        dialog.setStyleSheet("QDialog#report-preview { background: #ffffff; }")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title = QLabel("Предпросмотр таблицы")
        title.setObjectName("report-preview-title")
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        title.setStyleSheet(
            "background: #1f5e93; color: #ffffff; font-size: 14px; font-weight: 600; padding: 8px 12px;"
        )
        layout.addWidget(title)
        table = QTableWidget()
        table.setObjectName("report-preview-grid")
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setWordWrap(True)
        table.setShowGrid(True)
        table.verticalHeader().hide()
        table.setHorizontalHeader(PreviewHeader(table))
        table.setItemDelegateForColumn(0, _PreviewNameDelegate(table))
        catalog = self._catalog or {}
        columns = [item for item in catalog.get("columns") or [] if item["key"] in self._included_cols]
        parameters = self._preview_parameters()
        table.setColumnCount(2 + len(columns))
        table.setHorizontalHeaderLabels(
            ["Наименование параметра", "Ед. изм."] + [col.get("label") or "" for col in columns]
        )
        table.setRowCount(len(parameters))
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 340)
        table.setColumnWidth(1, 80)
        for index in range(2, table.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            header.setMinimumSectionSize(72)
        for row, param in enumerate(parameters):
            section = param.get("row_kind") in {"section", "computed"}
            name = QTableWidgetItem(_param_label(param))
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setData(Qt.ItemDataRole.UserRole, int(param.get("indent") or 0))
            name.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name.setBackground(QBrush(QColor(SECTION_BG if section else PARAM_BG)))
            if section:
                font = name.font()
                font.setBold(True)
                name.setFont(font)
            table.setItem(row, 0, name)
            unit_item = QTableWidgetItem(param.get("unit") or "" if param.get("row_kind") == "editable" else "")
            unit_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            unit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            unit_item.setBackground(QBrush(QColor(SECTION_BG if section else PARAM_BG)))
            if section:
                font = unit_item.font()
                font.setBold(True)
                unit_item.setFont(font)
            table.setItem(row, 1, unit_item)
            for col_index, column in enumerate(columns):
                cell = self._cells.get(f"{param.get('key')}:{column.get('key')}")
                item = QTableWidgetItem((cell or {}).get("display") or "")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                brush = _status_brush(cell, param.get("row_kind") or "editable")
                if brush:
                    item.setBackground(brush)
                table.setItem(row, 2 + col_index, item)
        table.resizeRowsToContents()
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 0)
        body_layout.addWidget(table, 1)
        layout.addWidget(body, 1)
        actions = QHBoxLayout()
        actions.setContentsMargins(16, 12, 16, 16)
        actions.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.reject)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        return dialog

    def _preview(self) -> None:
        dialog = self._build_preview()
        if dialog is not None:
            dialog.exec()

    def _export(self) -> None:
        params, cols = self._selected_keys()
        sheet_id = self.current_sheet_id()
        if sheet_id and params and cols:
            self.export_requested.emit(sheet_id, params, cols)
