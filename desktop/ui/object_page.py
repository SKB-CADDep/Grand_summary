from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPalette
from datetime import datetime

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _format_when(value: object) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return moment.astimezone().strftime("%d.%m.%Y %H:%M")


class ObjectPage(QWidget):
    object_selected = pyqtSignal(str)
    object_open_table_requested = pyqtSignal(str)
    import_parameters_requested = pyqtSignal()
    import_triangle_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._objects: list[dict] = []
        self._selected_id = ""
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        field = QWidget()
        field.setObjectName("guide-object")
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(5)
        field_layout.addWidget(QLabel("Объект"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Начните вводить название объекта")
        self.search.setMaximumWidth(720)
        self.search.textEdited.connect(self._on_typed)
        self.search.installEventFilter(self)
        field_layout.addWidget(self.search)
        field.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root.addWidget(field)

        self.popup = QFrame(self)
        self.popup.setObjectName("object-suggestions")
        self.popup.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestions = QListWidget()
        self.suggestions.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestions.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.suggestions.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.suggestions.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.suggestions.setWordWrap(True)
        palette = self.suggestions.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            palette.setColor(group, QPalette.ColorRole.Text, QColor("#263238"))
            palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#263238"))
            palette.setColor(group, QPalette.ColorRole.Highlight, QColor("#cfe6ff"))
            palette.setColor(group, QPalette.ColorRole.Base, QColor("#ffffff"))
        self.suggestions.setPalette(palette)
        self.suggestions.itemClicked.connect(self._pick)
        popup_layout.addWidget(self.suggestions)
        self.popup.hide()

        self.warn = QLabel()
        self.warn.setProperty("role", "warn")
        self.warn.hide()
        root.addWidget(self.warn)

        self.message = QLabel()
        self.message.setProperty("role", "ok")
        self.message.hide()
        root.addWidget(self.message)

        self.meta = QLabel("Без выбранного объекта таблица ИД и отчёт недоступны.")
        self.meta.setProperty("role", "hint")
        root.addWidget(self.meta)

        actions = QHBoxLayout()
        self.import_params_btn = QPushButton("Импортировать параметры объекта из Excel")
        self.import_triangle_btn = QPushButton("Импортировать из Excel (треугольники)")
        self.import_triangle_btn.setObjectName("guide-triangle")
        self.import_params_btn.clicked.connect(self.import_parameters_requested.emit)
        self.import_triangle_btn.clicked.connect(self.import_triangle_requested.emit)
        actions.addWidget(self.import_params_btn)
        actions.addWidget(self.import_triangle_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        summary_title = QLabel("Сводка работы с объектами")
        summary_title.setStyleSheet("font-weight: 600; font-size: 15px;")
        root.addWidget(summary_title)
        self.work_hint = QLabel("Пока ни один объект не взят в работу.")
        self.work_hint.setProperty("role", "hint")
        self.work_hint.setWordWrap(True)
        root.addWidget(self.work_hint)
        self.work_table = QTableWidget(0, 7)
        self.work_table.setHorizontalHeaderLabels(
            ["Объект", "Станция", "Турбина", "Листов", "Обновлено", "Кто изменил", "Кто начал"]
        )
        self.work_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.work_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.work_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.work_table.verticalHeader().setVisible(False)
        self.work_table.horizontalHeader().setStretchLastSection(True)
        self.work_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.work_table.cellDoubleClicked.connect(self._open_work_row)
        self.work_table.viewport().installEventFilter(self)
        root.addWidget(self.work_table, 1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hide_popup()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        table = getattr(self, "work_table", None)
        if table is not None and watched is table.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._clear_work_selection_if_empty(pos)
        if event.type() == QEvent.Type.MouseButtonPress and self.popup.isVisible():
            if isinstance(event, QMouseEvent):
                global_pos = event.globalPosition().toPoint()
            else:
                global_pos = getattr(event, "globalPos", lambda: QPoint())()
            if not self._click_inside_search_or_popup(global_pos):
                self._hide_popup()
        if watched is self.search:
            if event.type() == QEvent.Type.FocusIn:
                self._open_if_query()
            elif event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_Escape:
                    self._hide_popup()
                    return True
                if event.key() == Qt.Key.Key_Down and self.popup.isVisible() and self.suggestions.count():
                    row = self.suggestions.currentRow()
                    self.suggestions.setCurrentRow(min(row + 1, self.suggestions.count() - 1) if row >= 0 else 0)
                    return True
                if event.key() == Qt.Key.Key_Up and self.popup.isVisible() and self.suggestions.count():
                    row = self.suggestions.currentRow()
                    self.suggestions.setCurrentRow(max(row - 1, 0) if row >= 0 else 0)
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.popup.isVisible():
                    item = self.suggestions.currentItem() or self.suggestions.item(0)
                    if item:
                        self._pick(item)
                        return True
        return super().eventFilter(watched, event)

    def _click_inside_search_or_popup(self, global_pos: QPoint) -> bool:
        if self.search.rect().contains(self.search.mapFromGlobal(global_pos)):
            return True
        if self.popup.isVisible() and self.popup.rect().contains(self.popup.mapFromGlobal(global_pos)):
            return True
        return False

    def set_busy(self, busy: bool, can_write: bool, has_workbook: bool) -> None:
        self.search.setDisabled(busy)
        self.import_params_btn.setDisabled(busy or not can_write or not has_workbook)
        self.import_triangle_btn.setDisabled(busy or not can_write or not has_workbook)

    def set_objects(self, objects: list[dict], selected_id: str) -> None:
        self._objects = objects
        self._selected_id = selected_id
        selected = next((item for item in objects if item.get("id") == selected_id), None)
        self._updating = True
        if selected:
            self.search.setText(selected.get("name") or "")
        self._updating = False
        self._show_selected(selected)
        self._fill_work_summary()
        if selected:
            self._hide_popup()
        elif self.search.hasFocus() and self.search.text().strip():
            self._fill_and_show(self.search.text())
        else:
            self._hide_popup()

    def set_status(self, message: str = "", warn: str = "") -> None:
        self.message.setText(message)
        self.message.setVisible(bool(message))
        self.warn.setText(warn)
        self.warn.setVisible(bool(warn))

    def _show_selected(self, selected: dict | None) -> None:
        if not selected:
            self.meta.setText("Без выбранного объекта таблица ИД и отчёт недоступны.")
            self.warn.hide()
            return
        self.meta.setText(
            f"Станция: {selected.get('station') or '—'}; турбина: {selected.get('turbine') or '—'}; "
            f"ID_projects: {selected.get('external_id') or '—'}"
        )
        if selected.get("has_workbook"):
            self.warn.setText("По этому объекту работа уже начата. Открыта существующая сводка.")
            self.warn.show()
        else:
            self.warn.hide()

    def _matches(self, query: str) -> list[dict]:
        needle = query.strip().casefold()
        if not needle:
            return []
        return [item for item in self._objects if needle in (item.get("name") or "").casefold()][:30]

    def _on_typed(self, text: str) -> None:
        if self._updating:
            return
        selected = next((item for item in self._objects if item.get("id") == self._selected_id), None)
        if self._selected_id and selected and text != (selected.get("name") or ""):
            self._selected_id = ""
            self.object_selected.emit("")
        self._fill_and_show(text)

    def _open_if_query(self) -> None:
        if self.search.text().strip():
            self._fill_and_show(self.search.text())

    def _fill_and_show(self, text: str) -> None:
        matches = self._matches(text)
        self.suggestions.clear()
        for item in matches:
            label = item.get("name") or ""
            if item.get("has_workbook"):
                label += " (есть сводка)"
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, item.get("id"))
            row.setForeground(QBrush(QColor("#263238")))
            self.suggestions.addItem(row)
        if not matches:
            self._hide_popup()
            return
        self._place_popup()
        self.popup.show()
        self.popup.raise_()
        if self.suggestions.currentRow() < 0:
            self.suggestions.setCurrentRow(0)

    def _place_popup(self) -> None:
        origin = self.search.mapToGlobal(QPoint(0, self.search.height()))
        width = max(self.search.width(), 320)
        rows = min(self.suggestions.count(), 10)
        row_h = self.suggestions.sizeHintForRow(0) if self.suggestions.count() else 28
        height = min(280, max(36, rows * max(row_h, 28) + 4))
        screen = QApplication.screenAt(origin) or QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        if origin.y() + height > geo.bottom():
            origin = self.search.mapToGlobal(QPoint(0, -height))
        self.popup.setFixedSize(QSize(width, height))
        self.popup.move(origin)

    def _hide_popup(self) -> None:
        self.popup.hide()

    def _fill_work_summary(self) -> None:
        rows = [item for item in self._objects if item.get("has_workbook")]
        rows.sort(key=lambda item: str(item.get("workbook_updated_at") or ""), reverse=True)
        self.work_hint.setText(
            f"В работе {len(rows)} объект(ов) со статусом «есть сводка». Двойной щелчок открывает объект."
            if rows
            else "Пока ни один объект не взят в работу."
        )
        self.work_table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            values = [
                item.get("name") or "",
                item.get("station") or "—",
                item.get("turbine") or "—",
                str(item.get("sheet_count") or 1),
                _format_when(item.get("workbook_updated_at")),
                item.get("last_edited_by") or "—",
                item.get("started_by") or "—",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, item.get("id"))
                self.work_table.setItem(index, column, cell)
        self.work_table.resizeColumnsToContents()

    def _clear_work_selection_if_empty(self, pos) -> None:
        index = self.work_table.indexAt(pos)
        if index.isValid():
            return
        self.work_table.clearSelection()

    def _open_work_row(self, row: int, _column: int) -> None:
        item = self.work_table.item(row, 0)
        object_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if object_id:
            self.object_open_table_requested.emit(str(object_id))

    def _pick(self, item: QListWidgetItem) -> None:
        object_id = item.data(Qt.ItemDataRole.UserRole)
        if not object_id:
            return
        chosen = next((entry for entry in self._objects if entry.get("id") == object_id), None)
        self._updating = True
        self.search.setText((chosen or {}).get("name") or item.text())
        self._updating = False
        self._selected_id = str(object_id)
        self._hide_popup()
        self.object_selected.emit(str(object_id))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.popup.isVisible():
            self._place_popup()
