from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ObjectPage(QWidget):
    object_selected = pyqtSignal(str)
    object_create_requested = pyqtSignal(dict)
    import_parameters_requested = pyqtSignal()
    import_triangle_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._objects: list[dict] = []
        self._selected_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        search_row = QHBoxLayout()
        search_label = QLabel("Объект")
        self.search = QLineEdit()
        self.search.setObjectName("guide-object")
        self.search.setPlaceholderText("Начните вводить название объекта")
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(search_label)
        search_row.addWidget(self.search, 1)
        root.addLayout(search_row)

        self.suggestions = QListWidget()
        self.suggestions.setMaximumHeight(180)
        self.suggestions.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.suggestions.itemClicked.connect(self._pick)
        self.suggestions.hide()
        root.addWidget(self.suggestions)

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

        root.addWidget(QLabel("Создать объект"))
        form = QFormLayout()
        self.station_name = QLineEdit()
        self.station_number = QLineEdit()
        self.turbine_name = QLineEdit()
        self.factory_number = QLineEdit()
        self.series_turbines = QLineEdit()
        self.kind = QLineEdit()
        form.addRow("Наименование станции", self.station_name)
        form.addRow("Номер станции", self.station_number)
        form.addRow("Наименование турбины", self.turbine_name)
        form.addRow("Заводской номер", self.factory_number)
        form.addRow("Серия турбин", self.series_turbines)
        form.addRow("Тип объекта (kind)", self.kind)
        root.addLayout(form)

        self.create_btn = QPushButton("Создать объект")
        self.create_btn.clicked.connect(self._create)
        root.addWidget(self.create_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addStretch(1)

        for field in (
            self.station_name,
            self.station_number,
            self.turbine_name,
            self.factory_number,
            self.series_turbines,
            self.kind,
        ):
            field.textChanged.connect(self._update_create)

        self._update_create()

    def set_busy(self, busy: bool, can_write: bool, has_workbook: bool) -> None:
        self.search.setDisabled(busy)
        self.suggestions.setDisabled(busy)
        self.import_params_btn.setDisabled(busy or not can_write or not has_workbook)
        self.import_triangle_btn.setDisabled(busy or not can_write or not has_workbook)
        self.create_btn.setDisabled(busy or not can_write or not self._create_ready())

    def set_objects(self, objects: list[dict], selected_id: str) -> None:
        self._objects = objects
        self._selected_id = selected_id
        selected = next((item for item in objects if item.get("id") == selected_id), None)
        if selected:
            self.search.blockSignals(True)
            self.search.setText(selected.get("name") or "")
            self.search.blockSignals(False)
        self._filter(self.search.text())
        self._show_selected(selected)

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

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        self.suggestions.clear()
        if not query:
            self.suggestions.hide()
            return
        matches = [item for item in self._objects if query in (item.get("name") or "").casefold()][:30]
        for item in matches:
            label = item.get("name") or ""
            if item.get("has_workbook"):
                label += " (есть сводка)"
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, item.get("id"))
            self.suggestions.addItem(row)
        self.suggestions.setVisible(bool(matches))

    def _pick(self, item: QListWidgetItem) -> None:
        object_id = item.data(Qt.ItemDataRole.UserRole)
        if object_id:
            self.suggestions.hide()
            self.object_selected.emit(str(object_id))

    def _create_ready(self) -> bool:
        return all(
            field.text().strip()
            for field in (
                self.station_name,
                self.station_number,
                self.turbine_name,
                self.factory_number,
                self.series_turbines,
                self.kind,
            )
        )

    def _update_create(self) -> None:
        self.create_btn.setEnabled(self._create_ready())

    def _create(self) -> None:
        if not self._create_ready():
            return
        self.object_create_requested.emit(
            {
                "station_name": self.station_name.text().strip(),
                "station_number": self.station_number.text().strip(),
                "turbine_name": self.turbine_name.text().strip(),
                "factory_number": self.factory_number.text().strip(),
                "series_turbines": self.series_turbines.text().strip(),
                "kind": self.kind.text().strip(),
            }
        )
        for field in (
            self.station_name,
            self.station_number,
            self.turbine_name,
            self.factory_number,
            self.series_turbines,
            self.kind,
        ):
            field.clear()
