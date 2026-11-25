from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

FROZEN_COLUMNS = 4
HEADER_BG = QColor("#eef5fb")
HEADER_LINE = QColor("#d9e3f0")
HEADER_TEXT = QColor("#263238")


class StagesHeader(QHeaderView):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHighlightSections(False)

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        hint.setHeight(max(44, hint.height() * 2))
        return hint

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:  # noqa: N802
        painter.save()
        painter.fillRect(rect, HEADER_BG)
        painter.setPen(HEADER_LINE)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.setPen(HEADER_TEXT)
        model = self.model()
        text = str(model.headerData(logicalIndex, self.orientation()) or "") if model else ""
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        if logicalIndex == 1:
            painter.drawText(rect.adjusted(8, 2, -8, -2), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        elif logicalIndex < FROZEN_COLUMNS:
            painter.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignCenter, text)
        else:
            bottom = QRect(rect.left(), rect.top() + rect.height() // 2, rect.width(), rect.height() - rect.height() // 2)
            painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() <= FROZEN_COLUMNS:
            return
        first = self.sectionViewportPosition(FROZEN_COLUMNS)
        last_index = self.count() - 1
        last = self.sectionViewportPosition(last_index) + self.sectionSize(last_index)
        top = QRect(first, 0, max(0, last - first), self.height() // 2)
        painter = QPainter(self.viewport())
        painter.fillRect(top, HEADER_BG)
        painter.setPen(HEADER_LINE)
        painter.drawRect(top.adjusted(0, 0, -1, -1))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(HEADER_TEXT)
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, "Ступени")


class FrozenSheetTable(QTableWidget):
    frozen_cell_clicked = pyqtSignal(int, int)
    frozen_menu_requested = pyqtSignal(object)
    header_clicked = pyqtSignal(int)
    header_double_clicked = pyqtSignal(int)
    header_menu_requested = pyqtSignal(int, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("id-sheet")
        header = StagesHeader(Qt.Orientation.Horizontal, self)
        self.setHorizontalHeader(header)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.sectionClicked.connect(self.header_clicked.emit)
        header.sectionDoubleClicked.connect(self.header_double_clicked.emit)
        header.customContextMenuRequested.connect(self._header_menu)
        self._hide_row_numbers(self)
        self.setCornerButtonEnabled(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.horizontalHeader().setStretchLastSection(False)

        self.frozen = QTableWidget(self)
        self.frozen.setObjectName("id-sheet-frozen")
        frozen_header = StagesHeader(Qt.Orientation.Horizontal, self.frozen)
        self.frozen.setHorizontalHeader(frozen_header)
        self._hide_row_numbers(self.frozen)
        self.frozen.setCornerButtonEnabled(False)
        self.frozen.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.frozen.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.frozen.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.frozen.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.frozen.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.frozen.setWordWrap(False)
        self.frozen.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.frozen.cellClicked.connect(self.frozen_cell_clicked.emit)
        self.frozen.customContextMenuRequested.connect(self._frozen_menu)
        self.viewport().stackUnder(self.frozen)

        self._syncing_scroll = False
        self.horizontalHeader().sectionResized.connect(self._sync_column_width)
        self.verticalHeader().sectionResized.connect(self._sync_row_height)
        self.verticalScrollBar().valueChanged.connect(self._scroll_frozen)
        self.frozen.verticalScrollBar().valueChanged.connect(self._scroll_main)
        self.horizontalScrollBar().valueChanged.connect(self._sync_header_offset)
        self.horizontalHeader().sectionResized.connect(self._update_frozen_geometry)
        self._lock_header_scrollbars()

    def _frozen_menu(self, pos) -> None:
        self.frozen_menu_requested.emit(self.frozen.viewport().mapToGlobal(pos))

    def _header_menu(self, pos) -> None:
        header = self.horizontalHeader()
        self.header_menu_requested.emit(header.logicalIndexAt(pos), header.mapToGlobal(pos))

    def _sync_column_width(self, index: int, _old: int, new: int) -> None:
        if index < FROZEN_COLUMNS:
            self.frozen.setColumnWidth(index, new)
            self._update_frozen_geometry()

    def _sync_row_height(self, index: int, _old: int, new: int) -> None:
        self.frozen.setRowHeight(index, new)

    def _scroll_frozen(self, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.frozen.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def _scroll_main(self, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._lock_header_scrollbars()
        self._sync_header_offset(self.horizontalScrollBar().value())

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        super().scrollContentsBy(dx, dy)
        self._sync_header_offset(self.horizontalScrollBar().value())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._lock_header_scrollbars()
        self._sync_header_offset(self.horizontalScrollBar().value())
        self._update_frozen_geometry()

    def _lock_header_scrollbars(self) -> None:
        for header in (self.horizontalHeader(), self.frozen.horizontalHeader()):
            header.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            header.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            horizontal = header.horizontalScrollBar()
            vertical = header.verticalScrollBar()
            horizontal.setFixedHeight(0)
            vertical.setFixedWidth(0)
            horizontal.hide()
            vertical.hide()

    def _sync_header_offset(self, value: int) -> None:
        header = self.horizontalHeader()
        if header.offset() != value:
            header.setOffset(value)

    def _update_frozen_geometry(self) -> None:
        if self.columnCount() < FROZEN_COLUMNS:
            self.frozen.hide()
            return
        self.frozen.show()
        width = sum(self.columnWidth(index) for index in range(FROZEN_COLUMNS))
        self.frozen.setGeometry(
            self.frameWidth(),
            self.frameWidth(),
            width,
            self.viewport().height() + self.horizontalHeader().height(),
        )

    @staticmethod
    def _hide_row_numbers(grid: QTableWidget) -> None:
        header = grid.verticalHeader()
        header.hide()
        header.setMinimumWidth(0)
        header.setMaximumWidth(0)
        header.setFixedWidth(0)

    def sync_frozen(self) -> None:
        self._hide_row_numbers(self)
        self._hide_row_numbers(self.frozen)
        self.frozen.setRowCount(self.rowCount())
        self.frozen.setColumnCount(FROZEN_COLUMNS)
        labels = []
        for index in range(FROZEN_COLUMNS):
            item = self.horizontalHeaderItem(index)
            labels.append(item.text() if item else "")
        self.frozen.setHorizontalHeaderLabels(labels)
        for row in range(self.rowCount()):
            self.frozen.setRowHeight(row, self.rowHeight(row))
            for col in range(FROZEN_COLUMNS):
                source = self.item(row, col)
                clone = QTableWidgetItem(source.text() if source else "")
                if source:
                    clone.setFlags((source.flags() | Qt.ItemFlag.ItemIsSelectable) & ~Qt.ItemFlag.ItemIsEditable)
                    clone.setBackground(source.background())
                    clone.setForeground(source.foreground())
                    clone.setData(Qt.ItemDataRole.UserRole, source.data(Qt.ItemDataRole.UserRole))
                    clone.setData(Qt.ItemDataRole.UserRole + 3, source.data(Qt.ItemDataRole.UserRole + 3))
                    clone.setTextAlignment(source.textAlignment())
                self.frozen.setItem(row, col, clone)
        for col in range(FROZEN_COLUMNS):
            self.frozen.setColumnWidth(col, self.columnWidth(col))
        self.frozen.horizontalHeader().setFixedHeight(self.horizontalHeader().height())
        self._lock_header_scrollbars()
        self._sync_header_offset(self.horizontalScrollBar().value())
        self._update_frozen_geometry()

    def paint_frozen_item(self, row: int, column: int, item: QTableWidgetItem | None) -> None:
        if column >= FROZEN_COLUMNS or not item:
            return
        clone = self.frozen.item(row, column)
        if clone is None:
            return
        clone.setBackground(item.background())
        clone.setForeground(item.foreground())
        clone.setText(item.text())
