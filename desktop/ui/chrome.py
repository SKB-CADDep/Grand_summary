from __future__ import annotations

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.icons import redo_icon, undo_icon


class MenuBar(QFrame):
    refresh_requested = pyqtSignal()
    toggle_history_requested = pyqtSignal()
    history_position_requested = pyqtSignal(str)
    instruction_requested = pyqtSignal()
    about_requested = pyqtSignal()
    changelog_requested = pyqtSignal()
    journal_requested = pyqtSignal()
    guide_requested = pyqtSignal()
    notes_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("menubar", True)
        self.setObjectName("guide-menu")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)

        self.file_btn = self._menu_btn("Файл")
        self.file_menu = QMenu(self)
        self.file_menu.addAction("Обновить", self.refresh_requested.emit)
        self.file_btn.setMenu(self.file_menu)

        self.view_btn = self._menu_btn("Представление")
        self.view_menu = QMenu(self)
        self.view_menu.setObjectName("view-menu")
        self.history_toggle = self.view_menu.addAction("Скрыть панель истории", self.toggle_history_requested.emit)
        self.view_menu.addSeparator()
        pos = self.view_menu.addAction("Расположение панели")
        pos.setEnabled(False)
        self.hist_right = self.view_menu.addAction("✓ Справа", lambda: self.history_position_requested.emit("right"))
        self.hist_bottom = self.view_menu.addAction("Снизу", lambda: self.history_position_requested.emit("bottom"))
        self.view_btn.setMenu(self.view_menu)

        self.undo_btn = self._history_btn(undo_icon(), "Отменить", "Отменить (Ctrl+Z)")
        self.undo_btn.setObjectName("guide-undo")
        self.undo_btn.clicked.connect(self.undo_requested.emit)
        self.redo_btn = self._history_btn(redo_icon(), "Повторить", "Повторить (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo_requested.emit)

        self.help_btn = self._menu_btn("Справка")
        help_menu = QMenu(self)
        help_menu.addAction("Инструкция", self.instruction_requested.emit)
        help_menu.addAction("О приложении", self.about_requested.emit)
        help_menu.addAction("Журнал изменений приложения", self.changelog_requested.emit)
        help_menu.addAction("Журнал изменений пользователей", self.journal_requested.emit)
        help_menu.addAction("Обучение", self.guide_requested.emit)
        self.help_btn.setMenu(help_menu)

        self.notes_btn = self._menu_btn("Уведомления")
        self.notes_btn.setObjectName("guide-notes")
        self.notes_btn.clicked.connect(self.notes_requested.emit)

        self.guide_btn = QPushButton("?")
        self.guide_btn.setProperty("circle", True)
        self.guide_btn.setObjectName("guide-help")
        self.guide_btn.setToolTip("Обучение")
        self.guide_btn.setStyleSheet("font-weight: 700;")
        self.guide_btn.clicked.connect(self.guide_requested.emit)

        self.user_chip = QLabel("Пользователь: …")
        self.user_chip.setProperty("role", "user")
        self.user_chip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for widget in (
            self.file_btn,
            self.view_btn,
            self.undo_btn,
            self.redo_btn,
            self.help_btn,
            self.notes_btn,
            self.guide_btn,
        ):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(self.user_chip)

    def _menu_btn(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("flatMenu", True)
        button.setFlat(True)
        return button

    def _history_btn(self, icon: QIcon, name: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setProperty("historyNav", True)
        button.setIcon(icon)
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(34, 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAccessibleName(name)
        button.setToolTip(tip)
        return button

    def set_user(self, username: str, can_write: bool) -> None:
        suffix = "" if can_write else " (просмотр)"
        self.user_chip.setText(f"Пользователь: {username or '…'}{suffix}")

    def set_notes_count(self, unread: int) -> None:
        self.notes_btn.setText(f"Уведомления ({unread})" if unread else "Уведомления")

    def set_history_actions(self, can_undo: bool, can_redo: bool, undo_tip: str, redo_tip: str) -> None:
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)
        self.undo_btn.setToolTip(undo_tip)
        self.redo_btn.setToolTip(redo_tip)

    def set_history_prefs(self, open_panel: bool, position: str) -> None:
        self.history_toggle.setText("Скрыть панель истории" if open_panel else "Показать панель истории")
        self.hist_right.setText("✓ Справа" if position == "right" else "Справа")
        self.hist_bottom.setText("✓ Снизу" if position == "bottom" else "Снизу")


class TabStrip(QWidget):
    tab_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guide-tabs")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 14, 0)
        layout.setSpacing(6)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, obj in (
            ("object", "Объект и треугольники", None),
            ("table", "Таблица ИД", "guide-tab-table"),
            ("triangles", "Треугольники", None),
            ("report", "Отчёт", "guide-tab-report"),
        ):
            button = QPushButton(label)
            button.setProperty("tab", True)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFlat(True)
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            if obj:
                button.setObjectName(obj)
            button.clicked.connect(lambda _=False, tab=key: self.tab_changed.emit(tab))
            self.buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.buttons["object"].setChecked(True)
        self.buttons["object"].raise_()
        self.buttons["triangles"].hide()
        self._fitting_tabs = False
        self._fit_tab_buttons()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_tab_buttons()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.PaletteChange}:
            self._fit_tab_buttons()

    def _fit_tab_buttons(self) -> None:
        if getattr(self, "_fitting_tabs", False):
            return
        self._fitting_tabs = True
        try:
            self._apply_tab_widths()
        finally:
            self._fitting_tabs = False

    def _apply_tab_widths(self) -> None:
        for button in self.buttons.values():
            button.style().unpolish(button)
            button.style().polish(button)
            button.ensurePolished()
            font = QFont(button.font())
            font.setWeight(QFont.Weight.DemiBold)
            metrics = QFontMetrics(font)
            text_size = QSize(metrics.horizontalAdvance(button.text()), metrics.height())
            option = QStyleOptionButton()
            button.initStyleOption(option)
            option.state |= QStyle.StateFlag.State_On
            option.fontMetrics = metrics
            option.text = button.text()
            hint = button.style().sizeFromContents(
                QStyle.ContentsType.CT_PushButton,
                option,
                text_size,
                button,
            )
            button.setMinimumWidth(max(hint.width() + 8, text_size.width() + 48))

    def set_current(self, key: str) -> None:
        for name, button in self.buttons.items():
            button.blockSignals(True)
            button.setChecked(name == key)
            button.blockSignals(False)
        selected = self.buttons.get(key)
        if selected:
            selected.raise_()

    def set_enabled(self, workbook: bool, triangles: bool) -> None:
        self.buttons["table"].setEnabled(workbook)
        self.buttons["report"].setEnabled(workbook)
        self.buttons["triangles"].setVisible(workbook and triangles)
        self.buttons["triangles"].setEnabled(workbook)


class Workspace(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspace-card")
        self.setProperty("card", True)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(14, 14, 14, 14)
        self.layout_box.setSpacing(12)

    def set_page(self, widget: QWidget) -> None:
        while self.layout_box.count():
            item = self.layout_box.takeAt(0)
            if item.widget() and item.widget() is not widget:
                item.widget().setParent(self)
                item.widget().hide()
        widget.setParent(self)
        widget.show()
        self.layout_box.addWidget(widget)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
