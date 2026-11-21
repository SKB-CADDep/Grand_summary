from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.style import COMPUTED, CONFIRMED, DRAFT, HEADER_BG, PARAM_BG, SECTION_BG, UNIFIED

HEADER_LINE = QColor("#d9e3f0")
HEADER_TEXT = QColor("#263238")
INCLUDED_BG = QColor("#62d987")
INCLUDED_BD = QColor("#27934a")
INCLUDED_FG = QColor("#174d2b")
EXCLUDED_BG = QColor("#f3f5f8")
EXCLUDED_BD = QColor("#dfe4eb")
EXCLUDED_FG = QColor("#748094")
DIM = QColor("#9aa5b4")


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


class ReportHeader(QHeaderView):
    column_toggle_requested = pyqtSignal(int)

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
        if self.count() <= 3:
            return
        first = self.sectionViewportPosition(3)
        last_index = self.count() - 1
        last = self.sectionViewportPosition(last_index) + self.sectionSize(last_index)
        top = QRect(first, 0, max(0, last - first), self.height() // 3)
        painter = QPainter(self.viewport())
        painter.fillRect(top, QColor(HEADER_BG))
        painter.setPen(HEADER_LINE)
        painter.drawRect(top.adjusted(0, 0, -1, -1))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(HEADER_TEXT)
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, "Ступени")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        index = self.logicalIndexAt(pos)
        if index >= 3:
            section_x = self.sectionViewportPosition(index)
            rect = QRect(section_x, 0, self.sectionSize(index), self.height())
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
        self._sheet_id = ""
        self._busy = False

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
        self.type_combo.addItem("Исходные данные по проточной части", "short")
        self.type_combo.addItem("Исходные данные по облопачиванию", "full")
        self.type_combo.setMinimumWidth(280)
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
        if catalog and sheet_changed:
            confirmed = [cell for cell in cells if cell.get("status") == "confirmed"]
            param_keys = {item["key"] for item in catalog.get("parameters") or [] if item.get("row_kind") != "section"}
            col_keys = {item["key"] for item in catalog.get("columns") or []}
            self._included_params = {cell["parameter_key"] for cell in confirmed if cell.get("parameter_key") in param_keys}
            self._included_cols = {cell["column_key"] for cell in confirmed if cell.get("column_key") in col_keys}
        self._rebuild()
        self._refresh_actions()
        self.empty.setVisible(catalog is None)

    def current_sheet_id(self) -> str:
        return str(self.sheet_combo.currentData() or "")

    def current_type(self) -> str:
        return str(self.type_combo.currentData() or "short")

    def _sheet_changed(self) -> None:
        sheet_id = self.current_sheet_id()
        if sheet_id:
            self.preview_requested.emit(sheet_id, self.current_type())

    def _refresh_actions(self) -> None:
        ready = bool(self._included_params and self._included_cols and self._catalog)
        self.preview_btn.setDisabled(not ready)
        self.export_btn.setDisabled(self._busy or not ready)

    def _toggle_button(self, included: bool, tooltip: str, handler) -> QPushButton:
        button = QPushButton("+" if included else "−")
        button.setProperty("included", "true" if included else "false")
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        button.style().unpolish(button)
        button.style().polish(button)
        return button

    def _rebuild(self) -> None:
        catalog = self._catalog
        self.table.clear()
        if not catalog:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        columns = catalog.get("columns") or []
        parameters = catalog.get("parameters") or []
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
            if not section:
                included = param.get("key") in self._included_params
                label = _param_label(param)
                button = self._toggle_button(
                    included,
                    f"{'Убрать из отчёта' if included else 'Добавить в отчёт'}: {label}",
                    lambda _=False, key=param.get("key"): self._toggle_parameter(key),
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
            dim_row = not section and param.get("key") not in self._included_params
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
        header.update()
        header.viewport().update()

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
        catalog = self._catalog or {}
        selectable = [item for item in catalog.get("parameters") or [] if item.get("row_kind") != "section"]
        groups = {item.get("group") for item in selectable if item["key"] in self._included_params}
        return [
            item
            for item in catalog.get("parameters") or []
            if (item.get("row_kind") == "section" and item.get("key") in groups)
            or item.get("key") in self._included_params
        ]

    def _preview(self) -> None:
        params, cols = self._selected_keys()
        if not params or not cols:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Предпросмотр таблицы")
        dialog.resize(1100, 720)
        layout = QVBoxLayout(dialog)
        title = QLabel("Предпросмотр таблицы")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        catalog = self._catalog or {}
        columns = [item for item in catalog.get("columns") or [] if item["key"] in self._included_cols]
        parameters = self._preview_parameters()
        table.setColumnCount(2 + len(columns))
        table.setHorizontalHeaderLabels(["Наименование параметра", "Ед. изм."] + [col.get("label") or "" for col in columns])
        table.setRowCount(len(parameters))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for row, param in enumerate(parameters):
            section = param.get("row_kind") == "section"
            name = QTableWidgetItem(("    " * int(param.get("indent") or 0)) + _param_label(param))
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setBackground(QBrush(QColor(SECTION_BG if section else PARAM_BG)))
            if section:
                font = name.font()
                font.setBold(True)
                name.setFont(font)
            table.setItem(row, 0, name)
            unit_item = QTableWidgetItem(param.get("unit") or "" if param.get("row_kind") == "editable" else "")
            unit_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
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
        layout.addWidget(table, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        dialog.exec()

    def _export(self) -> None:
        params, cols = self._selected_keys()
        sheet_id = self.current_sheet_id()
        if sheet_id and params and cols:
            self.export_requested.emit(sheet_id, params, cols)
