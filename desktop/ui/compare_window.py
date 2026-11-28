from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.client import ApiClient, ApiError
from desktop.ui.style import configure_independent_window
from desktop.ui.table_page import TablePage


class SheetCompareWindow(QMainWindow):
    def __init__(
        self,
        client: ApiClient,
        source_id: str,
        source_name: str,
        sheets: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.source_id = source_id
        self.source_name = source_name
        self.sheets = list(sheets)
        self.setWindowTitle(f"Сравнение данных — {source_name}")
        configure_independent_window(self)
        self.resize(1180, 760)
        self.setMinimumSize(880, 560)

        host = QWidget()
        self.setCentralWidget(host)
        root = QVBoxLayout(host)
        root.setContentsMargins(12, 12, 12, 12)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        picker = QWidget()
        pick = QVBoxLayout(picker)
        heading = QLabel(f"Сравнить «{source_name}» с другими вкладками")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        pick.addWidget(heading)
        hint = QLabel("Отметьте таблицы и при необходимости задайте диапазон вкладок, затем откройте сравнение.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        pick.addWidget(hint)
        self.checks_host = QWidget()
        self.checks_layout = QVBoxLayout(self.checks_host)
        self.checks_layout.setContentsMargins(0, 0, 0, 0)
        self.checks_layout.setSpacing(4)
        self._boxes: list[QCheckBox] = []
        others = [sheet for sheet in self.sheets if str(sheet.get("id") or "") != source_id]
        if not others:
            empty = QLabel("Других вкладок для сравнения нет.")
            empty.setProperty("role", "hint")
            pick.addWidget(empty)
        for sheet in others:
            box = QCheckBox(sheet.get("name") or "")
            box.setProperty("sheet_id", sheet.get("id"))
            self.checks_layout.addWidget(box)
            self._boxes.append(box)
        self.checks_layout.addStretch(1)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setWidget(self.checks_host)
        pick.addWidget(scroller, 1)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Диапазон с"))
        self.range_from = QComboBox()
        self.range_to = QComboBox()
        for combo in (self.range_from, self.range_to):
            combo.addItem("не выбран", None)
            for sheet in self.sheets:
                combo.addItem(sheet.get("name") or "", sheet.get("id"))
        range_row.addWidget(self.range_from, 1)
        range_row.addWidget(QLabel("по"))
        range_row.addWidget(self.range_to, 1)
        pick.addLayout(range_row)
        self.pick_error = QLabel()
        self.pick_error.setProperty("role", "warn")
        self.pick_error.hide()
        pick.addWidget(self.pick_error)
        pick_buttons = QHBoxLayout()
        pick_buttons.addStretch(1)
        cancel = QPushButton("Закрыть")
        cancel.clicked.connect(self.close)
        show = QPushButton("Показать сравнение")
        show.clicked.connect(self._run_compare)
        pick_buttons.addWidget(cancel)
        pick_buttons.addWidget(show)
        pick.addLayout(pick_buttons)
        self.stack.addWidget(picker)

        result = QWidget()
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        back = QPushButton("К выбору таблиц")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.result_hint = QLabel()
        self.result_hint.setProperty("role", "hint")
        self.result_hint.setWordWrap(True)
        top.addWidget(back)
        top.addWidget(self.result_hint, 1)
        result_layout.addLayout(top)
        self.table_page = TablePage()
        self.table_page.configure_compare_view()
        self.table_page.history_needed.connect(self._load_history)
        self.table_page.last_comment_needed.connect(self._last_comment)
        result_layout.addWidget(self.table_page, 1)
        self.stack.addWidget(result)

    def selection(self) -> dict:
        return {
            "sheet_ids": [str(box.property("sheet_id")) for box in self._boxes if box.isChecked()],
            "range_from": self.range_from.currentData(),
            "range_to": self.range_to.currentData(),
            "combine": "or",
        }

    def _run_compare(self) -> None:
        body = self.selection()
        if not body["sheet_ids"] and not (body["range_from"] and body["range_to"]):
            self.pick_error.setText("Выберите вкладки или диапазон для сравнения.")
            self.pick_error.show()
            return
        self.pick_error.hide()
        try:
            payload = self.client.compare_sheet(self.source_id, body)
        except ApiError as exc:
            QMessageBox.warning(self, "Сравнение", str(exc))
            return
        self.show_result(payload)

    def show_result(self, payload: dict) -> None:
        targets = payload.get("targets") or []
        if not targets:
            self.pick_error.setText("Нет вкладок по выбранным условиям.")
            self.pick_error.show()
            return
        names = "», «".join(item.get("sheet_name") or "" for item in targets)
        changed = int(payload.get("changed_count") or 0)
        self.result_hint.setText(
            f"Оранжевым отмечены отличия «{self.source_name}» от: «{names}». Изменённых ячеек: {changed}."
        )
        book = payload.get("workbook") or {}
        self.table_page.set_data(
            object_name=self.source_name,
            catalog=payload.get("catalog"),
            workbook=book,
            unsaved=[],
            sheets=self.sheets,
            can_write=False,
            busy=False,
        )
        self.stack.setCurrentIndex(1)
        self.table_page.set_history_layout("right", True, {"right": 360, "bottom": 260})

    def _load_history(self, parameter_key: str, column_key: str) -> None:
        if self.client is None:
            return
        try:
            self.table_page.set_history(self.client.history(self.source_id, parameter_key, column_key))
        except ApiError:
            self.table_page.set_history([])

    def _last_comment(self, parameter_key: str, column_key: str) -> None:
        if self.client is None:
            return
        try:
            self.table_page.show_comment_tooltip(
                self.client.last_cell_comment(self.source_id, parameter_key, column_key)
            )
        except ApiError:
            self.table_page.show_comment_tooltip(None)
