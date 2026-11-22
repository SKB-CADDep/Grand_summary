from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

MIN_ROW = 11
MIN_COLUMN = 2
SKIP_TOP_ROWS = 7
SKIP_LEFT_COLUMNS = 1
FROZEN_HEADER_ROWS = 3
SELECTED_BG = QColor("#bbdefb")
SELECTED_BD = QColor("#1976d2")
SOURCE_BG = QColor("#ffffff")
MUTED_BG = QColor("#f3f7fc")
HEADER_BG = QColor("#eef5fb")


def is_source_cell(excel_row: int, excel_col: int) -> bool:
    return excel_row >= MIN_ROW and excel_col >= MIN_COLUMN


def excel_from_body(row: int, column: int) -> tuple[int, int]:
    return row + MIN_ROW, column + SKIP_LEFT_COLUMNS + 1


def excel_from_header(row: int, column: int) -> tuple[int, int]:
    return row + SKIP_TOP_ROWS + 1, column + SKIP_LEFT_COLUMNS + 1


def _caption_text(row: list) -> str:
    text = " ".join(" ".join(str(cell or "").split()) for cell in row if str(cell or "").strip())
    return text if text.casefold().startswith("таблица") else ""


def _visual_span(
    merge: list | tuple,
    excel_rows: list[int],
    excel_columns: list[int],
) -> tuple[int, int, int, int] | None:
    if len(merge) != 4:
        return None
    r1, c1, r2, c2 = (int(merge[0]), int(merge[1]), int(merge[2]), int(merge[3]))
    rows = [index for index, excel_row in enumerate(excel_rows) if r1 <= excel_row <= r2]
    cols = [index for index, excel_col in enumerate(excel_columns) if c1 <= excel_col <= c2]
    if not rows or not cols:
        return None
    if rows != list(range(rows[0], rows[0] + len(rows))):
        return None
    if cols != list(range(cols[0], cols[0] + len(cols))):
        return None
    if len(rows) == 1 and len(cols) == 1:
        return None
    return rows[0], cols[0], len(rows), len(cols)


def cell_key(sheet_key: str, excel_row: int, excel_col: int) -> str:
    return f"{sheet_key}:{excel_row}:{excel_col}"


class TriangleCellDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):  # noqa: N802
        selected = bool(option.state & QStyle.StateFlag.State_Selected) or bool(
            index.data(Qt.ItemDataRole.UserRole + 1)
        )
        source = bool(index.data(Qt.ItemDataRole.UserRole))
        header = bool(index.data(Qt.ItemDataRole.UserRole + 2))
        painter.save()
        if selected:
            painter.fillRect(option.rect, SELECTED_BG)
        elif header:
            painter.fillRect(option.rect, HEADER_BG)
        elif not source:
            painter.fillRect(option.rect, MUTED_BG)
        else:
            painter.fillRect(option.rect, SOURCE_BG)
        painter.setPen(QColor("#d9e3f0"))
        painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
        if selected:
            painter.setPen(QPen(SELECTED_BD, 2))
            painter.drawRect(option.rect.adjusted(2, 2, -3, -3))
        painter.setPen(QColor("#263238"))
        font = painter.font()
        if header:
            font.setBold(True)
            painter.setFont(font)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.drawText(
            option.rect.adjusted(4, 1, -4, -1),
            Qt.AlignmentFlag.AlignCenter,
            str(text),
        )
        painter.restore()


class TriangleGrid(QWidget):
    selection_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheet_key = ""
        self._building = False
        self._syncing_width = False
        self._excel_columns: list[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.caption = QLabel()
        self.caption.setObjectName("table-caption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.hide()
        layout.addWidget(self.caption)

        self.header = self._make_table(selectable=False)
        self.header.setObjectName("triangle-grid-header")
        self.header.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(0)
        header_row.addWidget(self.header, 1)
        self._header_pad = QWidget()
        header_row.addWidget(self._header_pad)
        layout.addLayout(header_row)

        self.body = self._make_table(selectable=True)
        self.body.setObjectName("triangle-grid")
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.body.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.body.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.body.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.body, 1)

        self.body.horizontalScrollBar().valueChanged.connect(self.header.horizontalScrollBar().setValue)
        self.header.horizontalScrollBar().valueChanged.connect(self.body.horizontalScrollBar().setValue)
        self.body.horizontalHeader().sectionResized.connect(self._sync_column_width)
        self.header.horizontalHeader().sectionResized.connect(self._sync_header_column_width)
        self.body.verticalScrollBar().rangeChanged.connect(lambda *_args: self._sync_header_pad())

    def _sync_header_pad(self) -> None:
        self._header_pad.setFixedWidth(max(16, self.body.verticalScrollBar().sizeHint().width()))

    def _make_table(self, selectable: bool) -> QTableWidget:
        table = QTableWidget()
        table.setItemDelegate(TriangleCellDelegate(table))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().hide()
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setFixedWidth(38)
        table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setCursor(Qt.CursorShape.PointingHandCursor if selectable else Qt.CursorShape.ArrowCursor)
        if not selectable:
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        return table

    def _sync_column_width(self, index: int, _old: int, new: int) -> None:
        if self._syncing_width or index >= self.header.columnCount():
            return
        self._syncing_width = True
        self.header.setColumnWidth(index, new)
        self._syncing_width = False

    def _sync_header_column_width(self, index: int, _old: int, new: int) -> None:
        if self._syncing_width or index >= self.body.columnCount():
            return
        self._syncing_width = True
        self.body.setColumnWidth(index, new)
        self._syncing_width = False

    def clear(self) -> None:
        self._building = True
        self.header.clear()
        self.body.clear()
        self.header.setRowCount(0)
        self.header.setColumnCount(0)
        self.body.setRowCount(0)
        self.body.setColumnCount(0)
        self.header.hide()
        self.caption.clear()
        self.caption.hide()
        self._building = False

    def fill(
        self,
        sheet_key: str,
        rows: list[list],
        selected: dict[str, dict],
        merged_ranges: list | None = None,
    ) -> None:
        self._sheet_key = sheet_key
        self._building = True
        width = max((len(row) for row in rows), default=0)
        caption = ""
        caption_index = -1
        for index, row in enumerate(rows[:15]):
            text = _caption_text(row)
            if text:
                caption = text
                caption_index = index
                break
        self.caption.setText(caption)
        self.caption.setVisible(bool(caption))
        header_indexes = [
            index
            for index in range(SKIP_TOP_ROWS, SKIP_TOP_ROWS + FROZEN_HEADER_ROWS)
            if index != caption_index and index < len(rows)
        ]
        header_rows = [rows[index] for index in header_indexes]
        body_rows = rows[MIN_ROW - 1 :]
        self._excel_columns = list(range(SKIP_LEFT_COLUMNS + 1, width + 1))

        header_excel_rows = [index + 1 for index in header_indexes]
        body_excel_rows = list(range(MIN_ROW, MIN_ROW + len(body_rows)))
        merges = merged_ranges or []
        header_spans = self._fill_part(
            self.header,
            header_rows,
            self._excel_columns,
            header_excel_rows,
            selectable=False,
            selected=selected,
            merged_ranges=merges,
        )
        body_spans = self._fill_part(
            self.body,
            body_rows,
            self._excel_columns,
            body_excel_rows,
            selectable=True,
            selected=selected,
            merged_ranges=merges,
        )
        self._apply_column_widths(header_spans, body_spans)
        header_height = sum(self.header.rowHeight(row) for row in range(self.header.rowCount()))
        if header_rows and self._excel_columns:
            self.header.setFixedHeight(header_height + 2)
            self.header.show()
        else:
            self.header.setFixedHeight(0)
            self.header.hide()
        self._sync_header_pad()
        self._building = False
        self._restore_selection(selected)
        self.selection_changed.emit()

    def _fill_part(
        self,
        table: QTableWidget,
        rows: list[list],
        excel_columns: list[int],
        excel_rows: list[int],
        selectable: bool,
        selected: dict[str, dict],
        merged_ranges: list,
    ) -> list[tuple[int, int, int, int]]:
        table.clear()
        table.clearSpans()
        table.setRowCount(len(rows))
        table.setColumnCount(len(excel_columns))
        numbers = table.verticalHeader()
        numbers.hide()
        numbers.setFixedWidth(0)
        for r, row in enumerate(rows):
            table.setRowHeight(r, 24)
            excel_row = excel_rows[r]
            for c, excel_col in enumerate(excel_columns):
                raw = row[excel_col - 1] if excel_col - 1 < len(row) else ""
                item = QTableWidgetItem(str(raw or ""))
                source = is_source_cell(excel_row, excel_col)
                flags = Qt.ItemFlag.ItemIsEnabled
                if selectable and source:
                    flags |= Qt.ItemFlag.ItemIsSelectable
                item.setFlags(flags)
                item.setData(Qt.ItemDataRole.UserRole, source)
                item.setData(Qt.ItemDataRole.UserRole + 1, cell_key(self._sheet_key, excel_row, excel_col) in selected)
                item.setData(Qt.ItemDataRole.UserRole + 2, not selectable)
                table.setItem(r, c, item)
        spans: list[tuple[int, int, int, int]] = []
        for merge in merged_ranges:
            visual = _visual_span(merge, excel_rows, excel_columns)
            if visual is None:
                continue
            row, column, row_span, col_span = visual
            table.setSpan(row, column, row_span, col_span)
            spans.append(visual)
        return spans

    def _apply_column_widths(
        self,
        header_spans: list[tuple[int, int, int, int]],
        body_spans: list[tuple[int, int, int, int]],
    ) -> None:
        count = len(self._excel_columns)
        if count == 0:
            return
        body_font = self.body.font()
        header_font = QFont(body_font)
        header_font.setBold(True)
        body_metrics = QFontMetrics(body_font)
        header_metrics = QFontMetrics(header_font)
        widths = [52] * count

        def consider(table: QTableWidget, spans: list[tuple[int, int, int, int]], metrics: QFontMetrics) -> None:
            wide = {(row, column) for row, column, _row_span, col_span in spans if col_span > 1}
            covered = {
                (row + row_offset, column + col_offset)
                for row, column, row_span, col_span in spans
                for row_offset in range(row_span)
                for col_offset in range(col_span)
                if (row_offset, col_offset) != (0, 0)
            }
            for row in range(table.rowCount()):
                for column in range(count):
                    if (row, column) in wide or (row, column) in covered:
                        continue
                    item = table.item(row, column)
                    if item and item.text():
                        widths[column] = max(widths[column], metrics.horizontalAdvance(item.text()) + 18)

        consider(self.header, header_spans, header_metrics)
        consider(self.body, body_spans, body_metrics)
        for table, spans, metrics in (
            (self.header, header_spans, header_metrics),
            (self.body, body_spans, body_metrics),
        ):
            for row, column, _row_span, col_span in spans:
                if col_span <= 1:
                    continue
                item = table.item(row, column)
                if not item or not item.text():
                    continue
                need = metrics.horizontalAdvance(item.text()) + 18
                have = sum(widths[column : column + col_span])
                if need <= have:
                    continue
                extra = need - have
                share, remainder = divmod(extra, col_span)
                for offset in range(col_span):
                    widths[column + offset] += share + (1 if offset < remainder else 0)
        for column, width in enumerate(widths):
            size = min(width, 420)
            self.body.setColumnWidth(column, size)
            self.header.setColumnWidth(column, size)

    def _restore_selection(self, selected: dict[str, dict]) -> None:
        self.body.clearSelection()
        for item in selected.values():
            if str(item.get("sheet_key") or "") != self._sheet_key:
                continue
            visual_row = int(item.get("row") or 0) - MIN_ROW
            try:
                visual_col = self._excel_columns.index(int(item.get("column") or 0))
            except ValueError:
                continue
            cell = self.body.item(visual_row, visual_col)
            if cell is not None:
                cell.setSelected(True)

    def current_sheet_selection(self) -> list[dict]:
        cells: list[dict] = []
        for index in self.body.selectedIndexes():
            excel_row = MIN_ROW + index.row()
            excel_col = self._excel_columns[index.column()]
            if not is_source_cell(excel_row, excel_col):
                continue
            cells.append({"sheet_key": self._sheet_key, "row": excel_row, "column": excel_col})
        return cells

    def _on_selection_changed(self) -> None:
        if self._building:
            return
        self.selection_changed.emit()


class TrianglePage(QWidget):
    catalog_needed = pyqtSignal(str)
    sync_requested = pyqtSignal(str, str, list, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheets: list[dict] = []
        self._targets: list[dict] = []
        self._catalog: dict | None = None
        self._selected: dict[str, dict] = {}
        self._can_write = False
        self._busy = False
        self._tab_buttons: list[QPushButton] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)
        title = QLabel("Треугольники")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        self.subtabs = QFrame()
        self.subtabs.setObjectName("triangle-subtabs")
        self.subtabs_layout = QHBoxLayout(self.subtabs)
        self.subtabs_layout.setContentsMargins(0, 0, 0, 0)
        self.subtabs_layout.setSpacing(4)
        self.subtabs_layout.addStretch(1)
        root.addWidget(self.subtabs)

        toolbar = QFrame()
        toolbar.setObjectName("triangle-toolbar")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(8)
        row1 = QHBoxLayout()
        target_label = QLabel("Лист ИД")
        target_label.setProperty("role", "hint")
        row1.addWidget(target_label)
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(180)
        self.target_combo.setMaximumWidth(240)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        row1.addWidget(self.target_combo)
        param_label = QLabel("Параметр для несопоставленных")
        param_label.setProperty("role", "hint")
        row1.addWidget(param_label)
        self.param_combo = QComboBox()
        self.param_combo.setMinimumWidth(180)
        self.param_combo.setMaximumWidth(260)
        row1.addWidget(self.param_combo)
        row1.addStretch(1)
        toolbar_layout.addLayout(row1)
        row2 = QHBoxLayout()
        self.sync_selected_btn = QPushButton("Перенести выделенное")
        self.sync_all_btn = QPushButton("Перенести всё")
        self.sync_selected_btn.clicked.connect(lambda: self._sync("selected"))
        self.sync_all_btn.clicked.connect(lambda: self._sync("all"))
        row2.addWidget(self.sync_selected_btn)
        row2.addWidget(self.sync_all_btn)
        self.count_label = QLabel("Выделено ячеек: 0")
        self.count_label.setProperty("role", "hint")
        row2.addWidget(self.count_label)
        hint = QLabel(
            "Клик выделяет ячейку, Shift — диапазон, Ctrl — отдельные ячейки, можно протянуть мышью. "
            "Основной лист ИД недоступен для записи."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        row2.addWidget(hint, 1)
        toolbar_layout.addLayout(row2)
        root.addWidget(toolbar)

        self.grid = TriangleGrid()
        self.grid.selection_changed.connect(self._capture_selection)
        root.addWidget(self.grid, 1)

        self.empty = QLabel("Нет импортированных листов треугольников.")
        self.empty.setProperty("role", "hint")
        self.empty.hide()
        root.addWidget(self.empty)

    def set_data(self, sheets: list[dict], targets: list[dict], can_write: bool, busy: bool) -> None:
        self._sheets = sheets
        self._targets = [item for item in targets if not item.get("is_primary")]
        self._can_write = can_write
        self._busy = busy
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
        self._fill_subtabs(current_key)
        self._rebuild_grid()
        self._target_changed()
        self._refresh_actions()
        self.target_combo.setDisabled(busy or not self._targets)
        self.param_combo.setDisabled(busy)
        self.empty.setVisible(not sheets)
        self.grid.setVisible(bool(sheets))

    def _fill_subtabs(self, current_key: str) -> None:
        while self.subtabs_layout.count() > 1:
            item = self.subtabs_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._tab_buttons = []
        for sheet in self._sheets:
            button = QPushButton(sheet.get("name") or sheet.get("key") or "")
            button.setProperty("sheetTab", True)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            key = str(sheet.get("key") or "")
            button.setChecked(key == current_key or (not current_key and not self._tab_buttons))
            button.clicked.connect(lambda _=False, sheet_key=key: self._select_sheet(sheet_key))
            self.subtabs_layout.insertWidget(self.subtabs_layout.count() - 1, button)
            self._tab_buttons.append(button)
        if self._tab_buttons and not any(button.isChecked() for button in self._tab_buttons):
            self._tab_buttons[0].setChecked(True)

    def _select_sheet(self, key: str) -> None:
        self._capture_selection()
        for button, sheet in zip(self._tab_buttons, self._sheets):
            button.setChecked(str(sheet.get("key") or "") == key)
        self._rebuild_grid()

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
        for button, sheet in zip(self._tab_buttons, self._sheets):
            if button.isChecked():
                return str(sheet.get("key") or "")
        return str(self._sheets[0].get("key") if self._sheets else "geometry")

    def _active_sheet(self) -> dict | None:
        key = self._active_key()
        return next((item for item in self._sheets if item.get("key") == key), self._sheets[0] if self._sheets else None)

    def _rebuild_grid(self) -> None:
        sheet = self._active_sheet()
        if not sheet:
            self.grid.clear()
            self._refresh_count()
            return
        self.grid.fill(
            str(sheet.get("key") or ""),
            sheet.get("rows") or [],
            self._selected,
            sheet.get("merged_ranges") or [],
        )
        self._refresh_count()

    def _capture_selection(self) -> None:
        sheet_key = self.grid._sheet_key
        if not sheet_key:
            return
        self._selected = {
            key: value
            for key, value in self._selected.items()
            if str(value.get("sheet_key") or "") != sheet_key
        }
        for cell in self.grid.current_sheet_selection():
            self._selected[cell_key(sheet_key, cell["row"], cell["column"])] = cell
        self._refresh_count()

    def _refresh_count(self) -> None:
        self.count_label.setText(f"Выделено ячеек: {len(self._selected)}")
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        enabled = self._can_write and not self._busy and bool(self.target_combo.currentData())
        self.sync_selected_btn.setEnabled(enabled and bool(self._selected))
        self.sync_all_btn.setEnabled(enabled)

    def _target_changed(self) -> None:
        target_id = self.target_combo.currentData()
        if target_id:
            self.catalog_needed.emit(str(target_id))

    def _sync(self, mode: str) -> None:
        target_id = self.target_combo.currentData()
        if not target_id:
            return
        self._capture_selection()
        cells = list(self._selected.values()) if mode == "selected" else []
        param = self.param_combo.currentData() or None
        self.sync_requested.emit(str(target_id), mode, cells, param)
