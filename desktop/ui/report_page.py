from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.style import CONFIRMED, DRAFT, COMPUTED


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

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Тип записки"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("Исходные данные по проточной части", "short")
        self.type_combo.addItem("Исходные данные по облопачиванию", "full")
        toolbar.addWidget(self.type_combo)
        toolbar.addWidget(QLabel("Лист таблицы ИД"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        toolbar.addWidget(self.sheet_combo)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.column_toggles = QHBoxLayout()
        root.addLayout(self.column_toggles)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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

    def set_table_data(self, catalog: dict | None, cells: list[dict], busy: bool = False) -> None:
        self._catalog = catalog
        self._cells = {f"{cell.get('parameter_key')}:{cell.get('column_key')}": cell for cell in cells}
        if catalog:
            self._included_params = {
                item["key"] for item in catalog.get("parameters") or [] if item.get("row_kind") != "section"
            }
            self._included_cols = {item["key"] for item in catalog.get("columns") or []}
        self._rebuild()
        self.preview_btn.setDisabled(busy or not catalog)
        self.export_btn.setDisabled(busy or not catalog)
        self.empty.setVisible(catalog is None)

    def current_sheet_id(self) -> str:
        return str(self.sheet_combo.currentData() or "")

    def current_type(self) -> str:
        return str(self.type_combo.currentData() or "short")

    def _sheet_changed(self) -> None:
        sheet_id = self.current_sheet_id()
        if sheet_id:
            self.preview_requested.emit(sheet_id, self.current_type())

    def _rebuild(self) -> None:
        catalog = self._catalog
        self.table.clear()
        if not catalog:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        columns = catalog.get("columns") or []
        parameters = catalog.get("parameters") or []
        while self.column_toggles.count():
            item = self.column_toggles.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.column_toggles.addWidget(QLabel("Столбцы:"))
        for column in columns:
            included = column.get("key") in self._included_cols
            button = QPushButton("+" if included else "−")
            button.setProperty("included", "true" if included else "false")
            button.style().unpolish(button)
            button.style().polish(button)
            button.setToolTip(column.get("label") or "")
            button.clicked.connect(lambda _=False, key=column.get("key"): self._toggle_column(key))
            self.column_toggles.addWidget(button)
        self.column_toggles.addStretch(1)
        self.table.setColumnCount(3 + len(columns))
        headers = [" ", "Наименование параметра", "Ед. изм."] + [col.get("label") or "" for col in columns]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(parameters))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, param in enumerate(parameters):
            if param.get("row_kind") != "section":
                included = param.get("key") in self._included_params
                button = QPushButton("+" if included else "−")
                button.setProperty("included", "true" if included else "false")
                button.style().unpolish(button)
                button.style().polish(button)
                button.clicked.connect(lambda _=False, key=param.get("key"): self._toggle_parameter(key))
                self.table.setCellWidget(row, 0, button)
            else:
                self.table.setItem(row, 0, QTableWidgetItem(""))
            label = param.get("label") or ""
            unit = param.get("unit") or ""
            if unit and label.endswith(f", {unit}"):
                label = label[: -len(unit) - 2].strip()
            name = QTableWidgetItem(("    " * int(param.get("indent") or 0)) + label)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 1, name)
            unit_item = QTableWidgetItem(unit if param.get("row_kind") == "editable" else "")
            unit_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 2, unit_item)
            for col_index, column in enumerate(columns):
                cell = self._cells.get(f"{param.get('key')}:{column.get('key')}")
                text = (cell or {}).get("display") or ""
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                status = "computed" if (cell or {}).get("locked") else (cell or {}).get("status") or "empty"
                if status == "draft":
                    item.setBackground(QBrush(QColor(DRAFT)))
                elif status == "confirmed":
                    item.setBackground(QBrush(QColor(CONFIRMED)))
                elif status in {"computed", "initial"} or param.get("row_kind") != "editable":
                    item.setBackground(QBrush(QColor(COMPUTED)))
                if column.get("key") not in self._included_cols:
                    item.setForeground(QBrush(QColor("#9aa5b4")))
                self.table.setItem(row, 3 + col_index, item)
            if param.get("key") not in self._included_params and param.get("row_kind") != "section":
                for col in range(self.table.columnCount()):
                    cell_item = self.table.item(row, col)
                    if cell_item:
                        cell_item.setForeground(QBrush(QColor("#9aa5b4")))

    def _toggle_parameter(self, key: str) -> None:
        if key in self._included_params:
            self._included_params.discard(key)
        else:
            self._included_params.add(key)
        self._rebuild()

    def _toggle_column(self, key: str) -> None:
        if key in self._included_cols:
            self._included_cols.discard(key)
        else:
            self._included_cols.add(key)
        self._rebuild()

    def _selected_keys(self) -> tuple[list[str], list[str]]:
        catalog = self._catalog or {}
        params = [item["key"] for item in catalog.get("parameters") or [] if item["key"] in self._included_params]
        cols = [item["key"] for item in catalog.get("columns") or [] if item["key"] in self._included_cols]
        return params, cols

    def _preview(self) -> None:
        params, cols = self._selected_keys()
        if not params or not cols:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Предпросмотр таблицы")
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        catalog = self._catalog or {}
        columns = [item for item in catalog.get("columns") or [] if item["key"] in self._included_cols]
        parameters = [item for item in catalog.get("parameters") or [] if item["key"] in self._included_params or item.get("row_kind") == "section"]
        table.setColumnCount(2 + len(columns))
        table.setHorizontalHeaderLabels(["Наименование параметра", "Ед. изм."] + [col.get("label") or "" for col in columns])
        table.setRowCount(len(parameters))
        for row, param in enumerate(parameters):
            if param.get("row_kind") == "section" and param.get("key") not in self._included_params:
                continue
            label = param.get("label") or ""
            unit = param.get("unit") or ""
            if unit and label.endswith(f", {unit}"):
                label = label[: -len(unit) - 2].strip()
            table.setItem(row, 0, QTableWidgetItem(label))
            table.setItem(row, 1, QTableWidgetItem(unit if param.get("row_kind") == "editable" else ""))
            for col_index, column in enumerate(columns):
                cell = self._cells.get(f"{param.get('key')}:{column.get('key')}")
                table.setItem(row, 2 + col_index, QTableWidgetItem((cell or {}).get("display") or ""))
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _export(self) -> None:
        params, cols = self._selected_keys()
        sheet_id = self.current_sheet_id()
        if sheet_id and params and cols:
            self.export_requested.emit(sheet_id, params, cols)
