from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

MIN_ROW = 11
MIN_COLUMN = 2
SELECTED_BG = QColor("#d7e8f8")


class TrianglePage(QWidget):
    catalog_needed = pyqtSignal(str)
    sync_requested = pyqtSignal(str, str, list, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheets: list[dict] = []
        self._targets: list[dict] = []
        self._catalog: dict | None = None
        self._selected: dict[str, dict] = {}
        self._building = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        title = QLabel("Треугольники")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        self.subtabs = QTabBar()
        self.subtabs.currentChanged.connect(self._rebuild_grid)
        root.addWidget(self.subtabs)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Лист ИД"))
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        toolbar.addWidget(self.target_combo)
        toolbar.addWidget(QLabel("Параметр для несопоставленных"))
        self.param_combo = QComboBox()
        toolbar.addWidget(self.param_combo)
        self.sync_selected_btn = QPushButton("Перенести выделенное")
        self.sync_all_btn = QPushButton("Перенести всё")
        self.sync_selected_btn.clicked.connect(lambda: self._sync("selected"))
        self.sync_all_btn.clicked.connect(lambda: self._sync("all"))
        toolbar.addWidget(self.sync_selected_btn)
        toolbar.addWidget(self.sync_all_btn)
        self.count_label = QLabel("Выделено ячеек: 0")
        toolbar.addWidget(self.count_label)
        hint = QLabel("Клик по ячейке выделяет её для переноса. Основной лист ИД недоступен для записи.")
        hint.setProperty("role", "hint")
        toolbar.addWidget(hint, 1)
        root.addLayout(toolbar)

        self.grid = QTableWidget()
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.cellClicked.connect(self._toggle_cell)
        root.addWidget(self.grid, 1)

    def set_data(self, sheets: list[dict], targets: list[dict], can_write: bool, busy: bool) -> None:
        self._sheets = sheets
        self._targets = [item for item in targets if not item.get("is_primary")]
        self.target_combo.blockSignals(True)
        current = self.target_combo.currentData()
        self.target_combo.clear()
        if not self._targets:
            self.target_combo.addItem("Нет листа для записи", "")
        for item in self._targets:
            self.target_combo.addItem(item.get("name") or "", item.get("id"))
        index = max(0, self.target_combo.findData(current))
        self.target_combo.setCurrentIndex(index)
        self.target_combo.blockSignals(False)
        current_key = self._active_key()
        self.subtabs.blockSignals(True)
        while self.subtabs.count():
            self.subtabs.removeTab(0)
        for sheet in sheets:
            self.subtabs.addTab(sheet.get("name") or sheet.get("key") or "")
        if sheets:
            wanted = next((i for i, sheet in enumerate(sheets) if sheet.get("key") == current_key), 0)
            self.subtabs.setCurrentIndex(wanted)
        self.subtabs.blockSignals(False)
        self._rebuild_grid()
        self._target_changed()
        enabled = can_write and not busy and bool(self.target_combo.currentData())
        self.sync_selected_btn.setEnabled(enabled and bool(self._selected))
        self.sync_all_btn.setEnabled(enabled)
        self.target_combo.setDisabled(busy or not self._targets)
        self.param_combo.setDisabled(busy)

    def set_catalog(self, catalog: dict | None) -> None:
        self._catalog = catalog
        current = self.param_combo.currentData()
        self.param_combo.blockSignals(True)
        self.param_combo.clear()
        self.param_combo.addItem("Не задан", "")
        for item in (catalog or {}).get("parameters") or []:
            if item.get("row_kind") == "editable":
                self.param_combo.addItem(item.get("label") or item.get("key"), item.get("key"))
        if current:
            index = self.param_combo.findData(current)
            if index >= 0:
                self.param_combo.setCurrentIndex(index)
        self.param_combo.blockSignals(False)

    def _active_key(self) -> str:
        index = self.subtabs.currentIndex()
        if 0 <= index < len(self._sheets):
            return str(self._sheets[index].get("key") or "")
        return str(self._sheets[0].get("key") if self._sheets else "geometry")

    def _active_sheet(self) -> dict | None:
        key = self._active_key()
        return next((item for item in self._sheets if item.get("key") == key), self._sheets[0] if self._sheets else None)

    def _rebuild_grid(self) -> None:
        sheet = self._active_sheet()
        self.grid.clear()
        if not sheet:
            self.grid.setRowCount(0)
            self.grid.setColumnCount(0)
            return
        rows: list[list] = sheet.get("rows") or []
        width = max((len(row) for row in rows), default=0)
        self.grid.setRowCount(len(rows))
        self.grid.setColumnCount(width)
        self.grid.setHorizontalHeaderLabels([str(i + 1) for i in range(width)])
        self.grid.setVerticalHeaderLabels([str(i + 1) for i in range(len(rows))])
        self._building = True
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(str(value or ""))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                key = f"{sheet.get('key')}:{r + 1}:{c + 1}"
                if key in self._selected:
                    item.setBackground(SELECTED_BG)
                self.grid.setItem(r, c, item)
        self._building = False
        self.grid.resizeColumnsToContents()
        self._refresh_count()

    def _toggle_cell(self, row: int, column: int) -> None:
        if self._building:
            return
        sheet = self._active_sheet()
        if not sheet:
            return
        if row + 1 < MIN_ROW or column + 1 < MIN_COLUMN:
            return
        key = f"{sheet.get('key')}:{row + 1}:{column + 1}"
        item = self.grid.item(row, column)
        if key in self._selected:
            del self._selected[key]
            if item:
                item.setBackground(QColor("#ffffff"))
        else:
            self._selected[key] = {"sheet_key": sheet.get("key"), "row": row + 1, "column": column + 1}
            if item:
                item.setBackground(SELECTED_BG)
        self._refresh_count()

    def _refresh_count(self) -> None:
        self.count_label.setText(f"Выделено ячеек: {len(self._selected)}")
        self.sync_selected_btn.setEnabled(bool(self._selected) and bool(self.target_combo.currentData()))

    def _target_changed(self) -> None:
        target_id = self.target_combo.currentData()
        if target_id:
            self.catalog_needed.emit(str(target_id))

    def _sync(self, mode: str) -> None:
        target_id = self.target_combo.currentData()
        if not target_id:
            return
        cells = list(self._selected.values()) if mode == "selected" else []
        param = self.param_combo.currentData() or None
        self.sync_requested.emit(str(target_id), mode, cells, param)
