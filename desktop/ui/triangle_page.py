from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.table_page import _is_table_caption, format_unit
from src.services.decimals import normalize_decimal_commas
from src.services.report_generation import parameter_display_label
from src.services.triangle_import import used_column_count

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
        self._column_tips: dict[int, str] = {}
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

        self.header_stage = self._make_stage_column(self.header)
        self.body_stage = self._make_stage_column(self.body)
        self.body_stage.cellClicked.connect(self._stage_body_clicked)
        self._syncing_scroll = False
        self.body.verticalScrollBar().valueChanged.connect(self._scroll_stage)
        self.body_stage.verticalScrollBar().valueChanged.connect(self._scroll_body)

        self.body.horizontalScrollBar().valueChanged.connect(self.header.horizontalScrollBar().setValue)
        self.header.horizontalScrollBar().valueChanged.connect(self.body.horizontalScrollBar().setValue)
        self.body.horizontalHeader().sectionResized.connect(self._sync_column_width)
        self.header.horizontalHeader().sectionResized.connect(self._sync_header_column_width)
        self.body.verticalScrollBar().rangeChanged.connect(lambda *_args: self._sync_header_pad())
        for table in (self.header, self.body, self.header_stage, self.body_stage):
            table.installEventFilter(self)
            table.viewport().installEventFilter(self)

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

    def _make_stage_column(self, table: QTableWidget) -> QTableWidget:
        frozen = QTableWidget(table)
        frozen.setObjectName("triangle-stage-column")
        frozen.setItemDelegate(TriangleCellDelegate(frozen))
        frozen.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        frozen.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        frozen.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        frozen.setFrameShape(QFrame.Shape.NoFrame)
        frozen.horizontalHeader().hide()
        frozen.verticalHeader().hide()
        frozen.verticalHeader().setFixedWidth(0)
        frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        frozen.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        frozen.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        frozen.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        frozen.setShowGrid(False)
        frozen.setWordWrap(False)
        frozen.hide()
        table.viewport().stackUnder(frozen)
        return frozen

    def _sync_column_width(self, index: int, _old: int, new: int) -> None:
        if self._syncing_width or index >= self.header.columnCount():
            return
        self._syncing_width = True
        self.header.setColumnWidth(index, new)
        self._syncing_width = False
        if index == 0:
            self._place_stage_column()

    def _sync_header_column_width(self, index: int, _old: int, new: int) -> None:
        if self._syncing_width or index >= self.body.columnCount():
            return
        self._syncing_width = True
        self.body.setColumnWidth(index, new)
        self._syncing_width = False
        if index == 0:
            self._place_stage_column()

    def clear(self) -> None:
        self._building = True
        self.header.clear()
        self.body.clear()
        self.header.setRowCount(0)
        self.header.setColumnCount(0)
        self.body.setRowCount(0)
        self.body.setColumnCount(0)
        self.header.hide()
        self.header_stage.hide()
        self.body_stage.hide()
        self.caption.clear()
        self.caption.hide()
        self._building = False

    def fill(
        self,
        sheet_key: str,
        rows: list[list],
        selected: dict[str, dict],
        merged_ranges: list | None = None,
        column_tips: dict[int, str] | None = None,
    ) -> None:
        self._sheet_key = sheet_key
        self._column_tips = dict(column_tips or {})
        self._building = True
        width = used_column_count(rows, merged_ranges)
        caption = ""
        caption_index = -1
        for index, row in enumerate(rows[:15]):
            text = _caption_text(row)
            if text:
                caption = text
                caption_index = index
                break
        self.caption.setText(format_unit(caption))
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
            column_tips=self._column_tips,
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
        self._sync_stage_column()
        self._building = False
        self._restore_selection(selected)
        self._paint_stage_selection()
        self.selection_changed.emit()

    def set_column_tips(self, column_tips: dict[int, str]) -> None:
        self._column_tips = dict(column_tips or {})
        for row in range(self.header.rowCount()):
            for visual, excel_col in enumerate(self._excel_columns):
                item = self.header.item(row, visual)
                if item is None:
                    continue
                tip = self._column_tips.get(excel_col) or ""
                if tip and item.text().strip() and self.header.columnSpan(row, visual) <= 1:
                    item.setToolTip(tip)
                else:
                    item.setToolTip("")
        self._sync_stage_column()

    def _scroll_stage(self, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.body_stage.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def _scroll_body(self, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.body.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def _sync_stage_column(self) -> None:
        self._copy_stage_column(self.header, self.header_stage)
        self._copy_stage_column(self.body, self.body_stage)
        self._place_stage_column()

    def _copy_stage_column(self, table: QTableWidget, frozen: QTableWidget) -> None:
        frozen.clear()
        frozen.clearSpans()
        if table.columnCount() < 1 or table.rowCount() < 1:
            frozen.hide()
            return
        frozen.setRowCount(table.rowCount())
        frozen.setColumnCount(1)
        covered_rows: set[int] = set()
        for row in range(table.rowCount()):
            frozen.setRowHeight(row, table.rowHeight(row))
            source = table.item(row, 0)
            column_span = table.columnSpan(row, 0)
            row_span = table.rowSpan(row, 0) if column_span <= 1 else 1
            clone = QTableWidgetItem("")
            if source is not None:
                clone.setData(Qt.ItemDataRole.UserRole + 2, source.data(Qt.ItemDataRole.UserRole + 2))
            if row not in covered_rows and source is not None and column_span <= 1:
                clone = QTableWidgetItem(source.text())
                clone.setFlags(source.flags())
                clone.setData(Qt.ItemDataRole.UserRole, source.data(Qt.ItemDataRole.UserRole))
                clone.setData(Qt.ItemDataRole.UserRole + 1, source.data(Qt.ItemDataRole.UserRole + 1))
                clone.setData(Qt.ItemDataRole.UserRole + 2, source.data(Qt.ItemDataRole.UserRole + 2))
                clone.setToolTip(source.toolTip())
                clone.setTextAlignment(source.textAlignment())
                if row_span > 1:
                    covered_rows.update(range(row + 1, row + row_span))
            elif source is not None:
                clone.setFlags(source.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            frozen.setItem(row, 0, clone)
        for row in range(table.rowCount()):
            row_span = table.rowSpan(row, 0)
            if table.columnSpan(row, 0) <= 1 and row_span > 1 and row not in covered_rows:
                frozen.setSpan(row, 0, row_span, 1)
        frozen.setColumnWidth(0, table.columnWidth(0))

    def _place_stage_column(self) -> None:
        for table, frozen in ((self.header, self.header_stage), (self.body, self.body_stage)):
            if table.columnCount() < 1 or table.rowCount() < 1:
                frozen.hide()
                continue
            header = table.horizontalHeader()
            vertical = table.verticalHeader()
            x = table.frameWidth() + (vertical.width() if vertical.isVisible() else 0)
            y = table.frameWidth() + (header.height() if header.isVisible() else 0)
            frozen.setGeometry(x, y, table.columnWidth(0), max(0, table.viewport().height()))
            frozen.setColumnWidth(0, table.columnWidth(0))
            frozen.show()
            frozen.raise_()

    def _paint_stage_selection(self) -> None:
        for row in range(self.body.rowCount()):
            source = self.body.item(row, 0)
            clone = self.body_stage.item(row, 0)
            if source is None or clone is None:
                continue
            clone.setData(Qt.ItemDataRole.UserRole + 1, source.isSelected())

    def _stage_body_clicked(self, row: int, _column: int) -> None:
        item = self.body.item(row, 0)
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsSelectable:
            return
        modifiers = QApplication.keyboardModifiers()
        if not modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.body.clearSelection()
        item.setSelected(not item.isSelected() if modifiers & Qt.KeyboardModifier.ControlModifier else True)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if watched in (self.header, self.header.viewport(), self.body, self.body.viewport()):
                self._place_stage_column()
        if event.type() == QEvent.Type.Wheel and watched in (
            self.header_stage.viewport(),
            self.body_stage.viewport(),
        ):
            QApplication.sendEvent(self.body.viewport(), event)
            return True
        return super().eventFilter(watched, event)

    def _fill_part(
        self,
        table: QTableWidget,
        rows: list[list],
        excel_columns: list[int],
        excel_rows: list[int],
        selectable: bool,
        selected: dict[str, dict],
        merged_ranges: list,
        column_tips: dict[int, str] | None = None,
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
                item = QTableWidgetItem(format_unit(normalize_decimal_commas(str(raw or "")) or ""))
                source = is_source_cell(excel_row, excel_col)
                flags = Qt.ItemFlag.ItemIsEnabled
                if selectable and source:
                    flags |= Qt.ItemFlag.ItemIsSelectable
                item.setFlags(flags)
                item.setData(Qt.ItemDataRole.UserRole, source)
                item.setData(Qt.ItemDataRole.UserRole + 1, cell_key(self._sheet_key, excel_row, excel_col) in selected)
                item.setData(Qt.ItemDataRole.UserRole + 2, not selectable)
                tip = (column_tips or {}).get(excel_col) or ""
                if tip and str(raw or "").strip():
                    item.setToolTip(tip)
                table.setItem(r, c, item)
        spans: list[tuple[int, int, int, int]] = []
        for merge in merged_ranges:
            visual = _visual_span(merge, excel_rows, excel_columns)
            if visual is None:
                continue
            row, column, row_span, col_span = visual
            table.setSpan(row, column, row_span, col_span)
            if col_span > 1:
                origin = table.item(row, column)
                if origin is not None:
                    origin.setToolTip("")
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
        self._paint_stage_selection()
        self.selection_changed.emit()


class ParameterTreeCombo(QFrame):
    """Выпадающее дерево параметров по столбцу «Наименование параметра»."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("parameter-tree-combo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self.setMinimumHeight(36)
        self._key = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(0)
        self._label = QLabel("Не задан")
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._label, 1)
        chevron = QLabel()
        chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        chevron.setPixmap(QPixmap(str(Path(__file__).resolve().parent / "chevron-down.png")))
        layout.addWidget(chevron)

        self._popup = QFrame(self, Qt.WindowType.Popup)
        self._popup.setObjectName("parameter-tree-popup")
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(8, 8, 8, 8)
        popup_layout.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        self._search.returnPressed.connect(self._accept_search)
        popup_layout.addWidget(self._search)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(False)
        self._tree.itemClicked.connect(self._item_clicked)
        popup_layout.addWidget(self._tree, 1)
        self._popup.setStyleSheet(
            "QFrame#parameter-tree-popup { background: #ffffff; border: 1px solid #d9e3f0; border-radius: 8px; }"
            "QTreeWidget { border: none; background: #ffffff; outline: none; }"
            "QTreeWidget::item { padding: 3px 2px; color: #263238; }"
            "QTreeWidget::item:selected { background: #dbeafe; color: #263238; }"
            "QTreeWidget::item:hover { background: #f3f7fc; }"
        )

    def currentData(self):  # noqa: N802
        return self._key

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.show_popup()
        super().mousePressEvent(event)

    def show_popup(self) -> None:
        self._search.clear()
        self._apply_filter("")
        self._reveal_current()
        self._popup.setFixedSize(max(self.width(), 440), 420)
        self._popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self._popup.show()
        self._search.setFocus()

    def set_parameters(self, parameters: list[dict]) -> None:
        keep = self._key
        self._tree.clear()
        unset = QTreeWidgetItem(["Не задан"])
        unset.setData(0, Qt.ItemDataRole.UserRole, "")
        self._tree.addTopLevelItem(unset)
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for param in parameters:
            label = param.get("label") or ""
            if _is_table_caption(label):
                continue
            title = format_unit(parameter_display_label(param) or label or param.get("key") or "")
            item = QTreeWidgetItem([title])
            editable = param.get("row_kind") == "editable" and bool(param.get("key"))
            item.setData(0, Qt.ItemDataRole.UserRole, param.get("key") if editable else "")
            if not editable:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            indent = int(param.get("indent") or 0)
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            stack.append((indent, item))
        self._select_key(keep)

    def _select_key(self, key: str) -> None:
        self._key = ""
        self._label.setText("Не задан")
        if not key:
            return
        match = self._find_item(key)
        if match is None:
            return
        self._key = key
        self._label.setText(match.text(0))

    def _find_item(self, key: str) -> QTreeWidgetItem | None:
        stack = [self._tree.topLevelItem(index) for index in range(self._tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                return item
            stack.extend(item.child(index) for index in range(item.childCount()))
        return None

    def _reveal_current(self) -> None:
        item = self._find_item(self._key) if self._key else None
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._tree.scrollToItem(item)
        self._tree.setCurrentItem(item)

    def _item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.text(0) == "Не задан" and item.parent() is None:
            self._select_key("")
            self._popup.hide()
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        self._select_key(str(key))
        self._popup.hide()

    def _apply_filter(self, text: str) -> None:
        query = text.casefold().strip()

        def walk(item: QTreeWidgetItem, ancestor_match: bool) -> bool:
            if item.text(0) == "Не задан" and item.parent() is None:
                item.setHidden(False)
                return True
            self_match = bool(query) and query in item.text(0).casefold()
            show_branch = ancestor_match or self_match
            child_match = False
            for index in range(item.childCount()):
                if walk(item.child(index), show_branch):
                    child_match = True
            visible = not query or show_branch or child_match
            item.setHidden(not visible)
            if query and (self_match or child_match):
                item.setExpanded(True)
            elif not query:
                item.setExpanded(False)
            return visible

        for index in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(index), False)
        if not query:
            self._reveal_current()

    def _accept_search(self) -> None:
        visible = self._visible_choices()
        if len(visible) == 1:
            self._item_clicked(visible[0], 0)

    def _visible_choices(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.isHidden():
                return
            if item.data(0, Qt.ItemDataRole.UserRole):
                found.append(item)
            for index in range(item.childCount()):
                walk(item.child(index))

        for index in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(index))
        return found


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
        self.param_combo = ParameterTreeCombo()
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
        self._targets = [
            item
            for item in targets
            if item.get("is_primary") and not item.get("is_issued") and not item.get("is_base")
        ]
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
        self.param_combo.set_parameters((catalog or {}).get("parameters") or [])
        sheet = self._active_sheet()
        if sheet:
            self.grid.set_column_tips(self._column_tips(sheet))

    def _column_tips(self, sheet: dict) -> dict[int, str]:
        parameters = {
            item.get("key"): item for item in (self._catalog or {}).get("parameters") or []
        }
        tips: dict[int, str] = {}
        for column, keys in (sheet.get("coordinate_mapping") or {}).items():
            names = []
            for key in keys or []:
                param = parameters.get(key)
                if not param:
                    continue
                name = parameter_display_label(param) or param.get("label") or ""
                if name:
                    names.append(format_unit(name))
            if names:
                tips[int(column)] = "Таблица ИД: " + "\n".join(names) if len(names) == 1 else "Таблица ИД:\n" + "\n".join(names)
        return tips

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
            self._column_tips(sheet),
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
