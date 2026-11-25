from __future__ import annotations

import re
from html import escape

from PyQt6.QtCore import QEvent, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.icons import eye_icon, flag_icon, pencil_icon
from desktop.ui.sheet_table import FROZEN_COLUMNS, FrozenSheetTable
from desktop.ui.style import COMPUTED, CONFIRMED, DRAFT, HIGHLIGHT, IMPORTED, PARAM_BG, PRIMARY, SECTION_BG, TRIANGLE, UNIFIED
from src.services.report_generation import parameter_designation, parameter_display_label

PARAM_ROLE = Qt.ItemDataRole.UserRole
COLUMN_ROLE = Qt.ItemDataRole.UserRole + 1
OPTIONS_ROLE = Qt.ItemDataRole.UserRole + 2
KIND_ROLE = Qt.ItemDataRole.UserRole + 3
DATA_COLUMN = FROZEN_COLUMNS
UNIT_ROLE = Qt.ItemDataRole.UserRole + 4
STAGE_WIDTH_TEXT = "Единичные НЛ"
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_UNIT_TOKEN = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])((?:мм|см|дм|км|м|с))(?:\^)?([−\-])?(\d+)(?![A-Za-zА-Яа-яЁё])",
    re.IGNORECASE,
)


def format_unit(value: str) -> str:
    """Показывает степень в единице верхним индексом: мм2 → мм², м-1 → м⁻¹."""
    text = value or ""
    if not text:
        return ""

    def replace(match: re.Match[str]) -> str:
        sign = "⁻" if match.group(2) else ""
        return match.group(1) + sign + match.group(3).translate(_SUPERSCRIPT_DIGITS)

    return _UNIT_TOKEN.sub(replace, text)


def _is_table_caption(label: str) -> bool:
    text = " ".join((label or "").split()).casefold()
    if not text.startswith("таблица"):
        return False
    rest = text[len("таблица") :].lstrip(" .–-—")
    return bool(rest[:1].isdigit())


def _status_color(cell: dict | None, row_kind: str, show_changes: bool = True) -> QColor | None:
    if row_kind != "editable":
        return QColor(COMPUTED)
    if not cell:
        return None
    if cell.get("locked"):
        return QColor(COMPUTED)
    if cell.get("unified"):
        return QColor(UNIFIED)
    status = cell.get("status") or "empty"
    if not show_changes:
        return None
    if status == "draft":
        return QColor(DRAFT)
    if status == "confirmed":
        return QColor(CONFIRMED)
    if status == "triangle":
        return QColor(TRIANGLE)
    if cell.get("excel_highlight"):
        return QColor(IMPORTED)
    if status == "computed":
        return QColor(COMPUTED)
    return None


def _show_option_matches(combo: QComboBox, text: str) -> None:
    completer = combo.completer()
    if completer is None:
        return
    completer.setCompletionPrefix(text)
    popup = completer.popup()
    popup.setMinimumWidth(max(combo.width(), 240))
    if text and completer.completionCount() == 0:
        popup.hide()
        return
    completer.complete()


def _option_editor(parent: QWidget, options: list) -> QComboBox:
    values = [str(value) for value in options if str(value).strip()]
    combo = QComboBox(parent)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.setMaxVisibleItems(12)
    combo.addItem("")
    combo.addItems(values)
    completer = QCompleter(values, combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)
    line = combo.lineEdit()
    if line is not None:
        line.textEdited.connect(lambda text, box=combo: _show_option_matches(box, text))
    return combo


class CellDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):  # noqa: N802
        options = index.data(OPTIONS_ROLE) or []
        if options:
            return _option_editor(parent, options)
        editor = QLineEdit(parent)
        editor.setFrame(False)
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        text = index.data(Qt.ItemDataRole.EditRole) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        if isinstance(editor, QComboBox):
            pos = editor.findText(str(text))
            if pos >= 0:
                editor.setCurrentIndex(pos)
            else:
                editor.setEditText(str(text))
            QTimer.singleShot(0, lambda box=editor: _show_option_matches(box, box.currentText()))
            return
        editor.setText(str(text))

    def setModelData(self, editor, model, index):  # noqa: N802
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
            return
        model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)


class SheetTabBar(QFrame):
    sheet_selected = pyqtSignal(str)
    menu_requested = pyqtSignal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sheet-tabs")
        self.buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(3)
        self._row = QWidget()
        self._row_layout = QHBoxLayout(self._row)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(3)
        self._row_layout.addStretch(1)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setFixedHeight(38)
        scroller.setWidget(self._row)
        layout.addWidget(scroller)

    def set_sheets(self, sheets: list[dict], current_id: str | None) -> None:
        while self._row_layout.count() > 1:
            item = self._row_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.buttons = {}
        for sheet in sheets:
            sheet_id = str(sheet.get("id") or "")
            label = sheet.get("name") or ""
            if sheet.get("is_primary"):
                label = f"{label} · основной"
            button = QPushButton(label)
            if sheet.get("is_issued"):
                button.setIcon(flag_icon())
                button.setToolTip("Версия выдана")
            button.setProperty("sheetTab", True)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            bold = QFont(button.font())
            bold.setWeight(QFont.Weight.DemiBold)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(label) + 28)
            button.setChecked(sheet_id == current_id)
            button.setEnabled(not bool(self.property("busy")))
            button.clicked.connect(lambda _=False, sid=sheet_id: self.sheet_selected.emit(sid))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, sid=sheet_id, btn=button: self.menu_requested.emit(sid, btn.mapToGlobal(pos))
            )
            self._row_layout.insertWidget(self._row_layout.count() - 1, button)
            self.buttons[sheet_id] = button


class TablePage(QWidget):
    save_project_requested = pyqtSignal()
    import_workbook_requested = pyqtSignal()
    clear_excel_highlight_requested = pyqtSignal()
    export_current_requested = pyqtSignal()
    export_all_requested = pyqtSignal()
    compose_report_requested = pyqtSignal()
    sheet_selected = pyqtSignal(str)
    sheet_copy_requested = pyqtSignal(str)
    sheet_rename_requested = pyqtSignal(str)
    sheet_primary_requested = pyqtSignal(str)
    sheet_ordinary_requested = pyqtSignal(str)
    sheet_delete_requested = pyqtSignal(str)
    sheet_issued_requested = pyqtSignal(str)
    draft_requested = pyqtSignal(str, str, str, object)
    confirm_requested = pyqtSignal(str, str, str, str, object)
    discard_requested = pyqtSignal(str, str)
    comment_requested = pyqtSignal(str, str, str)
    unify_requested = pyqtSignal(str, str, bool)
    history_needed = pyqtSignal(str, str)
    last_comment_needed = pyqtSignal(str, str)
    add_parameter_requested = pyqtSignal(dict)
    update_parameter_requested = pyqtSignal(str, dict)
    delete_parameter_requested = pyqtSignal(str)
    add_column_requested = pyqtSignal(str)
    update_column_requested = pyqtSignal(str, str)
    delete_column_requested = pyqtSignal(str)
    cell_selected = pyqtSignal(str, str)
    save_all_drafts_requested = pyqtSignal()
    history_panel_toggled = pyqtSignal(bool)
    history_position_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog: dict | None = None
        self.workbook: dict | None = None
        self.unsaved: list[dict] = []
        self.sheets: list[dict] = []
        self.history_items: list[dict] = []
        self.can_write = False
        self.busy = False
        self.table_mode = "view"
        self.structure_edit = False
        self._cells: dict[str, dict] = {}
        self._rebuilding = False
        self._selected: tuple[str, str] | None = None
        self._find_hits: list[tuple[int, int]] = []
        self._find_index = 0
        self._hover_keys: tuple[str, str] | None = None
        self._draft_save_target: tuple[str, str] | None = None
        self._history_sizes = {"right": 360, "bottom": 260}
        self._shown_parameters: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(self.title, 1)
        self.save_btn = QPushButton("Сохранить проект")
        self.import_btn = QPushButton("Импортировать .xlsx")
        self.export_sheet_btn = QPushButton("Выгрузить лист")
        self.export_all_btn = QPushButton("Выгрузить всё")
        self.report_btn = QPushButton("Составить отчет")
        self.save_btn.clicked.connect(self.save_project_requested.emit)
        self.import_btn.clicked.connect(self.import_workbook_requested.emit)
        self.export_sheet_btn.clicked.connect(self.export_current_requested.emit)
        self.export_all_btn.clicked.connect(self.export_all_requested.emit)
        self.report_btn.clicked.connect(self.compose_report_requested.emit)
        for button in (
            self.save_btn,
            self.import_btn,
            self.export_sheet_btn,
            self.export_all_btn,
            self.report_btn,
        ):
            header.addWidget(button)
        root.addLayout(header)

        toolbar_wrap = QWidget()
        toolbar_wrap.setObjectName("guide-colors")
        toolbar = QHBoxLayout(toolbar_wrap)
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.view_btn = QPushButton()
        self.edit_btn = QPushButton()
        self.view_btn.setIcon(eye_icon())
        self.edit_btn.setIcon(pencil_icon())
        self.view_btn.setProperty("modeBtn", True)
        self.edit_btn.setProperty("modeBtn", True)
        self.view_btn.setToolTip("Режим просмотра")
        self.edit_btn.setToolTip("Режим редактирования")
        self.view_btn.setCheckable(True)
        self.edit_btn.setCheckable(True)
        self.view_btn.setChecked(True)
        self.view_btn.clicked.connect(lambda: self.set_mode("view"))
        self.edit_btn.clicked.connect(lambda: self.set_mode("edit"))
        self.mode_box = QWidget()
        self.mode_box.setObjectName("guide-table-mode")
        mode_layout = QHBoxLayout(self.mode_box)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(4)
        mode_layout.addWidget(self.view_btn)
        mode_layout.addWidget(self.edit_btn)
        toolbar.addWidget(self.mode_box)
        self.mode_hint = QLabel()
        self.mode_hint.setProperty("role", "hint")
        toolbar.addWidget(self.mode_hint, 1)
        self.unsaved_label = QLabel()
        toolbar.addWidget(self.unsaved_label)
        self.structure_btn = QPushButton("Редактировать структуру")
        self.structure_btn.setObjectName("guide-add-param")
        self.structure_btn.clicked.connect(self._toggle_structure)
        toolbar.addWidget(self.structure_btn)
        root.addWidget(toolbar_wrap)

        self.structure_box = QWidget()
        struct = QVBoxLayout(self.structure_box)
        struct.setContentsMargins(0, 0, 0, 0)
        row1 = QHBoxLayout()
        self.struct_label = QLineEdit()
        self.struct_label.setPlaceholderText("Наименование")
        self.struct_unit = QLineEdit()
        self.struct_unit.setPlaceholderText("Ед. изм.")
        self.struct_unit.setMaximumWidth(90)
        self.struct_indent = QComboBox()
        self.struct_indent.addItem("0 — группа", 0)
        self.struct_indent.addItem("1", 1)
        self.struct_indent.addItem("2", 2)
        self.struct_indent.setCurrentIndex(1)
        save_row_btn = QPushButton("Сохранить строку")
        add_row_btn = QPushButton("Добавить")
        add_child_btn = QPushButton("Добавить вложенный")
        delete_row_btn = QPushButton("Удалить")
        save_row_btn.clicked.connect(self._save_parameter)
        add_row_btn.clicked.connect(self._add_parameter)
        add_child_btn.clicked.connect(self._add_child)
        delete_row_btn.clicked.connect(self._delete_parameter)
        for widget in (
            self.struct_label,
            self.struct_unit,
            QLabel("Уровень"),
            self.struct_indent,
            save_row_btn,
            add_row_btn,
            add_child_btn,
            delete_row_btn,
        ):
            row1.addWidget(widget)
        struct.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Шапка таблицы"))
        self.column_combo = QComboBox()
        self.column_combo.currentIndexChanged.connect(self._column_picked)
        self.column_label = QLineEdit()
        self.column_label.setPlaceholderText("Наименование столбца")
        save_col_btn = QPushButton("Сохранить название")
        delete_col_btn = QPushButton("Удалить столбец")
        self.new_column = QLineEdit()
        self.new_column.setPlaceholderText("Новый столбец")
        add_col_btn = QPushButton("Добавить столбец")
        save_col_btn.clicked.connect(self._save_column)
        delete_col_btn.clicked.connect(self._delete_column)
        add_col_btn.clicked.connect(self._add_column)
        for widget in (
            self.column_combo,
            self.column_label,
            save_col_btn,
            delete_col_btn,
            self.new_column,
            add_col_btn,
        ):
            row2.addWidget(widget)
        struct.addLayout(row2)
        self.structure_panel = QScrollArea()
        self.structure_panel.setWidgetResizable(True)
        self.structure_panel.setFrameShape(QFrame.Shape.NoFrame)
        self.structure_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.structure_panel.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.structure_panel.setFixedHeight(96)
        self.structure_panel.setWidget(self.structure_box)
        self.structure_panel.hide()
        root.addWidget(self.structure_panel)

        self.find_bar = QWidget()
        find_row = QHBoxLayout(self.find_bar)
        find_row.setContentsMargins(0, 0, 0, 0)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Найти…")
        self.find_input.textChanged.connect(self._find)
        prev_btn = QPushButton("↑")
        next_btn = QPushButton("↓")
        close_find = QPushButton("Закрыть")
        prev_btn.clicked.connect(lambda: self._step_find(-1))
        next_btn.clicked.connect(lambda: self._step_find(1))
        close_find.clicked.connect(self.find_bar.hide)
        self.find_count = QLabel()
        find_row.addWidget(self.find_input)
        find_row.addWidget(prev_btn)
        find_row.addWidget(next_btn)
        find_row.addWidget(self.find_count)
        find_row.addWidget(close_find)
        self.find_bar.hide()
        root.addWidget(self.find_bar)
        QShortcut(QKeySequence.StandardKey.Find, self, self._open_find)

        self.sheet_bar = SheetTabBar()
        self.sheet_bar.setObjectName("guide-sheet")
        self.sheet_bar.sheet_selected.connect(self._sheet_changed)
        self.sheet_bar.menu_requested.connect(self._sheet_menu_at)
        root.addWidget(self.sheet_bar)

        self.table_caption = QLabel()
        self.table_caption.setObjectName("table-caption")
        self.table_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table_caption.setWordWrap(True)
        self.table_caption.hide()
        root.addWidget(self.table_caption)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Horizontal)
        self.table = FrozenSheetTable()
        self.table.setObjectName("guide-table")
        self.table.setItemDelegate(CellDelegate(self.table))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(self._cell_double)
        self.table.itemChanged.connect(self._item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._cell_menu)
        self.table.frozen_cell_clicked.connect(self._cell_clicked)
        self.table.frozen_menu_requested.connect(self._frozen_menu)
        self.table.header_clicked.connect(self._header_clicked)
        self.table.header_double_clicked.connect(self._header_double_clicked)
        self.table.header_menu_requested.connect(self._header_menu)
        self.table.currentCellChanged.connect(self._current_changed)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.cellEntered.connect(self._cell_entered)
        split.addWidget(self.table)

        self.split = split
        self.history_panel = QWidget()
        self.history_panel.setObjectName("guide-edit")
        hist = QVBoxLayout(self.history_panel)
        hist.setContentsMargins(8, 0, 0, 0)
        hist.setSpacing(8)
        hist_header = QHBoxLayout()
        title = QLabel("История изменений")
        title.setStyleSheet("font-weight: 600;")
        hist_header.addWidget(title)
        hist.addLayout(hist_header)
        self.cell_caption = QLabel()
        self.cell_caption.setWordWrap(True)
        hist.addWidget(self.cell_caption)
        self.edit_row = QWidget()
        edit_layout = QVBoxLayout(self.edit_row)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("Ссылка на документ (прячется в номере)")
        self.link_edit.editingFinished.connect(self._save_link_draft)
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("Комментарий (обязателен)")
        btn_row = QHBoxLayout()
        self.confirm_btn = QPushButton("Сохранить значение")
        self.discard_btn = QPushButton("Отменить черновик")
        self.confirm_btn.clicked.connect(self._confirm)
        self.discard_btn.clicked.connect(self._discard)
        btn_row.addWidget(self.confirm_btn)
        btn_row.addWidget(self.discard_btn)
        edit_layout.addWidget(self.link_edit)
        edit_layout.addWidget(self.comment_edit)
        edit_layout.addLayout(btn_row)
        hist.addWidget(self.edit_row)
        self.link_view = QLabel()
        self.link_view.setProperty("role", "hint")
        self.link_view.setTextFormat(Qt.TextFormat.RichText)
        self.link_view.setOpenExternalLinks(True)
        self.link_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.link_view.hide()
        hist.addWidget(self.link_view)
        self.view_hint = QLabel("Чтобы изменить значение, включите режим редактирования.")
        self.view_hint.setProperty("role", "hint")
        hist.addWidget(self.view_hint)
        self.lock_hint = QLabel()
        self.lock_hint.setProperty("role", "hint")
        hist.addWidget(self.lock_hint)
        self.comment_box = QWidget()
        comment_layout = QVBoxLayout(self.comment_box)
        comment_layout.setContentsMargins(0, 0, 0, 0)
        self.comment_label = QLabel("Комментарий к ячейке")
        self.cell_comment = QPlainTextEdit()
        self.cell_comment.setPlaceholderText("Введите комментарий")
        self.cell_comment.setMaximumHeight(70)
        comment_btns = QHBoxLayout()
        self.add_comment_btn = QPushButton("Добавить комментарий")
        cancel_comment = QPushButton("Отмена")
        self.add_comment_btn.clicked.connect(self._submit_comment)
        cancel_comment.clicked.connect(self._cancel_comment)
        comment_btns.addWidget(self.add_comment_btn)
        comment_btns.addWidget(cancel_comment)
        comment_layout.addWidget(self.comment_label)
        comment_layout.addWidget(self.cell_comment)
        comment_layout.addLayout(comment_btns)
        self.comment_box.hide()
        hist.addWidget(self.comment_box)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Когда", "Кто", "Было", "Стало", "Комментарий"])
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hist.addWidget(self.history_table, 1)
        self.history_empty = QLabel("Выберите ячейку, чтобы увидеть историю. Правка доступна в режиме редактирования.")
        self.history_empty.setProperty("role", "hint")
        hist.addWidget(self.history_empty)
        self.history_panel.setMinimumWidth(280)
        self.history_panel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_panel.customContextMenuRequested.connect(self._history_menu)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self._history_menu)
        self.history_table.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.viewport().customContextMenuRequested.connect(self._history_menu)
        self.history_panel.installEventFilter(self)
        split.addWidget(self.history_panel)
        split.setStretchFactor(0, 1)
        split.setSizes([900, 360])
        root.addWidget(split, 1)
        self._history_position = "right"
        self._comment_mode = False

        self.empty = QLabel("Сначала выберите объект на вкладке «Объект и треугольники».")
        self.empty.setProperty("role", "hint")
        root.addWidget(self.empty)

    def _view_only(self) -> bool:
        book = self.workbook or {}
        return bool(book.get("is_primary") or book.get("is_issued"))

    def set_mode(self, mode: str) -> None:
        if self._view_only():
            mode = "view"
        self.table_mode = mode
        locked = self._view_only()
        self.edit_btn.setVisible(not locked)
        self.view_btn.setChecked(mode == "view" or locked)
        self.edit_btn.setChecked(mode == "edit" and not locked)
        self.view_btn.setProperty("active", mode == "view")
        self.edit_btn.setProperty("active", mode == "edit")
        self.view_btn.style().unpolish(self.view_btn)
        self.view_btn.style().polish(self.view_btn)
        self.edit_btn.style().unpolish(self.edit_btn)
        self.edit_btn.style().polish(self.edit_btn)
        if mode != "edit":
            self.structure_edit = False
            self.structure_panel.hide()
        self._apply_edit_triggers()
        self._refresh_hints()

    def set_data(
        self,
        *,
        object_name: str,
        catalog: dict | None,
        workbook: dict | None,
        unsaved: list[dict],
        sheets: list[dict],
        can_write: bool,
        busy: bool,
    ) -> None:
        self.catalog = catalog
        self.workbook = workbook
        self.unsaved = unsaved
        self.sheets = sheets
        self.can_write = can_write
        self.busy = busy
        self.title.setText(object_name or "")
        self._cells = {
            f"{cell.get('parameter_key')}:{cell.get('column_key')}": cell for cell in (workbook or {}).get("cells") or []
        }
        has_book = catalog is not None and workbook is not None
        self.empty.setVisible(not has_book)
        self.table.setVisible(has_book)
        self.sheet_bar.setVisible(has_book)
        writable = can_write and not busy and has_book
        self.save_btn.setEnabled(writable)
        self.import_btn.setEnabled(writable)
        self.export_sheet_btn.setEnabled(has_book and not busy)
        self.export_all_btn.setEnabled(has_book and not busy)
        self.report_btn.setEnabled(has_book and not busy)
        if workbook and (workbook.get("is_primary") or workbook.get("is_issued")):
            self.set_mode("view")
        locked = self._view_only()
        self.edit_btn.setVisible(not locked)
        self.edit_btn.setEnabled(can_write and not locked)
        self.structure_btn.setVisible(writable and not locked)
        if self.structure_edit and self.table_mode == "edit":
            self.structure_panel.show()
        else:
            self.structure_panel.hide()
        self._fill_sheets()
        self._fill_columns()
        self._rebuild_table()
        self._refresh_hints()

    def set_history_layout(self, position: str, opened: bool, sizes: dict) -> None:
        self._history_position = position
        self._history_sizes = {
            "right": int(sizes.get("right") or 360),
            "bottom": int(sizes.get("bottom") or 260),
        }
        self.history_panel.setVisible(opened)
        if not opened:
            return
        if position == "bottom":
            self.split.setOrientation(Qt.Orientation.Vertical)
            self.split.setSizes([max(200, 800 - self._history_sizes["bottom"]), self._history_sizes["bottom"]])
        else:
            self.split.setOrientation(Qt.Orientation.Horizontal)
            self.split.setSizes([max(400, 1280 - self._history_sizes["right"]), self._history_sizes["right"]])

    def _set_history_visible(self, opened: bool) -> None:
        self.set_history_layout(self._history_position, opened, self._history_sizes)
        self.history_panel_toggled.emit(opened)

    def show_comment_tooltip(self, text: str | None) -> None:
        if text:
            self.table.setToolTip(text)
        else:
            self.table.setToolTip("")

    def set_history(self, items: list[dict]) -> None:
        items = sorted(items, key=lambda item: item.get("created_at") or "")
        self.history_items = items
        self.history_table.setRowCount(len(items) or 1)
        if not items:
            self.history_table.setItem(0, 0, QTableWidgetItem("История пуста"))
            self.history_table.setSpan(0, 0, 1, 5)
            return
        self.history_table.clearSpans()
        for row, item in enumerate(items):
            values = [
                item.get("created_at") or "",
                item.get("author") or "",
                item.get("old_value") or "",
                item.get("new_value") or "",
                item.get("comment") or "",
            ]
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.history_table.resizeColumnsToContents()

    def current_cell(self) -> tuple[str, str] | None:
        return self._selected

    def _has_excel_highlight(self) -> bool:
        return any(cell.get("excel_highlight") for cell in self._cells.values())

    def _add_clear_highlight_action(self, menu: QMenu) -> None:
        if not self._has_excel_highlight():
            return
        menu.addSeparator()
        action = menu.addAction("Снять оранжевую подсветку", self.clear_excel_highlight_requested.emit)
        action.setEnabled(self.can_write and not self.busy)

    def _refresh_hints(self) -> None:
        if (self.workbook or {}).get("is_primary"):
            self.mode_hint.setText("Основной лист доступен только для просмотра.")
        elif (self.workbook or {}).get("is_issued"):
            self.mode_hint.setText("Версия выдана. Лист доступен только для просмотра.")
        elif self.table_mode == "edit":
            if self._has_excel_highlight():
                self.mode_hint.setText("Оранжевый — история из Excel, жёлтый — черновик, зелёный — сохранено.")
            else:
                self.mode_hint.setText("Жёлтый — черновик, зелёный — сохранено, серый — группа или заблокировано правилом.")
        elif self._has_excel_highlight():
            self.mode_hint.setText("Оранжевым отмечены изменения между листами Excel. Снять подсветку можно правой кнопкой мыши.")
        else:
            self.mode_hint.setText("Просмотр: значения не меняются. Чтобы править ячейки, включите режим редактирования.")
        if self.unsaved:
            self.unsaved_label.setText(f"Несохранено ячеек: {len(self.unsaved)}")
            self.unsaved_label.setProperty("role", "warn")
        else:
            self.unsaved_label.setText("Несохранённых ячеек нет")
            self.unsaved_label.setProperty("role", "hint")
        self.unsaved_label.style().unpolish(self.unsaved_label)
        self.unsaved_label.style().polish(self.unsaved_label)
        self.structure_btn.setText("Готово" if self.structure_edit else "Редактировать структуру")

    def _apply_edit_triggers(self) -> None:
        editing = self.table_mode == "edit" and self.can_write and not self._view_only()
        if editing:
            self.table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            )
        else:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def _fill_sheets(self) -> None:
        self.sheet_bar.setProperty("busy", self.busy)
        self.sheet_bar.set_sheets(self.sheets, (self.workbook or {}).get("id"))

    def _fill_columns(self) -> None:
        current = self.column_combo.currentData()
        self.column_combo.blockSignals(True)
        self.column_combo.clear()
        for column in (self.catalog or {}).get("columns") or []:
            self.column_combo.addItem(column.get("label") or column.get("key"), column.get("key"))
        if current:
            index = self.column_combo.findData(current)
            if index >= 0:
                self.column_combo.setCurrentIndex(index)
        self._column_picked()
        self.column_combo.blockSignals(False)

    def apply_cell(self, cell: dict, unsaved: list[dict] | None = None) -> None:
        if unsaved is not None:
            self.unsaved = unsaved
        param = cell.get("parameter_key")
        column = cell.get("column_key")
        if not param or not column:
            self._refresh_hints()
            return
        self._cells[f"{param}:{column}"] = cell
        text = cell.get("display") or cell.get("draft_value") or cell.get("value") or ""
        parameters = self._shown_parameters
        columns = (self.catalog or {}).get("columns") or []
        row = next((index for index, item in enumerate(parameters) if item.get("key") == param), -1)
        col = next((index for index, item in enumerate(columns) if item.get("key") == column), -1)
        if row < 0 or col < 0:
            self._refresh_hints()
            return
        item = self.table.item(row, DATA_COLUMN + col)
        if item is None:
            self._refresh_hints()
            return
        self.table.blockSignals(True)
        try:
            if item.text() != str(text):
                item.setText(str(text))
            color = _status_color(
                cell,
                parameters[row].get("row_kind") or "editable",
                show_changes=not (self.workbook or {}).get("is_issued"),
            )
            item.setBackground(QBrush(color) if color else QBrush())
            self._decorate_cell_item(item, cell, selected=self._selected == (param, column))
            if self._selected == (param, column):
                self.discard_btn.setEnabled(cell.get("status") == "draft")
                self._show_cell_link(cell)
        finally:
            self.table.blockSignals(False)
        self._refresh_hints()

    def _hide_row_numbers(self) -> None:
        for grid in (self.table, self.table.frozen):
            header = grid.verticalHeader()
            header.setVisible(False)
            header.setFixedWidth(0)
            grid.setCornerButtonEnabled(False)

    def _parameter_column_width(self) -> int:
        header_font = QFont(self.table.font())
        header_font.setBold(True)
        header_font.setPointSize(10)
        width = QFontMetrics(header_font).horizontalAdvance("Наименование параметра") + 28
        metrics = QFontMetrics(self.table.font())
        item = self._name_width_item()
        if item is None:
            for row in range(self.table.rowCount()):
                current = self.table.item(row, 1)
                if current is not None:
                    width = max(width, metrics.horizontalAdvance(current.text()) + 28)
            return width
        return max(width, metrics.horizontalAdvance(item.text()) + 28)

    def _name_width_item(self) -> QTableWidgetItem | None:
        for row, param in enumerate(self._shown_parameters):
            if int(param.get("excel_row") or 0) == 7 or param.get("key") == "r007":
                return self.table.item(row, 1)
        if self.table.rowCount() >= 7:
            return self.table.item(6, 1)
        return None

    def _stage_width_row(self) -> int | None:
        for row, param in enumerate(self._shown_parameters):
            if int(param.get("excel_row") or 0) == 15 or param.get("key") == "r015":
                return row
        if self.table.rowCount() >= 15:
            return 14
        return None

    def _stage_column_width(self) -> int:
        metrics = QFontMetrics(self.table.font())
        width = metrics.horizontalAdvance(STAGE_WIDTH_TEXT) + 20
        row = self._stage_width_row()
        if row is None:
            return width
        for index, column in enumerate((self.catalog or {}).get("columns") or []):
            if column.get("kind") not in (None, "", "stage"):
                continue
            item = self.table.item(row, DATA_COLUMN + index)
            if item is not None and item.text():
                width = max(width, metrics.horizontalAdvance(item.text()) + 20)
        return width

    def _number_column_width(self) -> int:
        header_font = QFont(self.table.font())
        header_font.setBold(True)
        header_font.setPointSize(10)
        width = QFontMetrics(header_font).horizontalAdvance("№") + 20
        metrics = QFontMetrics(self.table.font())
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.text():
                width = max(width, metrics.horizontalAdvance(item.text()) + 16)
        return width

    def _designation_column_width(self) -> int:
        header_font = QFont(self.table.font())
        header_font.setBold(True)
        header_font.setPointSize(10)
        width = QFontMetrics(header_font).horizontalAdvance("Обозначение") + 28
        metrics = QFontMetrics(self.table.font())
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 2)
            if item is not None and item.text():
                width = max(width, metrics.horizontalAdvance(item.text()) + 28)
        return width

    def _rebuild_table(self) -> None:
        catalog = self.catalog
        self._rebuilding = True
        self.table.blockSignals(True)
        try:
            self.table.clear()
            if not catalog:
                self._shown_parameters = []
                self.table_caption.clear()
                self.table_caption.hide()
                self.table.setRowCount(0)
                self.table.setColumnCount(0)
                return
            columns = catalog.get("columns") or []
            titles: list[str] = []
            parameters = []
            for param in catalog.get("parameters") or []:
                label = param.get("label") or ""
                if _is_table_caption(label):
                    titles.append(" ".join(label.split()))
                else:
                    parameters.append(param)
            if not titles:
                sheet_name = (self.workbook or {}).get("sheet_name") or ""
                if _is_table_caption(sheet_name):
                    titles.append(" ".join(sheet_name.split()))
            self._shown_parameters = parameters
            self.table_caption.setText("\n".join(titles))
            self.table_caption.setVisible(bool(titles))
            self.table.setColumnCount(DATA_COLUMN + len(columns))
            self.table.setRowCount(len(parameters))
            self.table.setHorizontalHeaderLabels(
                ["№", "Наименование параметра", "Обозначение", "Ед. изм."] + [col.get("label") or "" for col in columns]
            )
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(1, 80)
            header.setMinimumSectionSize(48)
            self.table.verticalHeader().setDefaultSectionSize(22)
            self._hide_row_numbers()
            number = 0
            for row, param in enumerate(parameters):
                unit = param.get("unit") or ""
                editable = param.get("row_kind") == "editable"
                if editable:
                    number += 1
                row_bg = QBrush(QColor(SECTION_BG if not editable else PARAM_BG))
                number_item = QTableWidgetItem(str(number) if editable else "")
                number_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                number_item.setBackground(row_bg)
                self.table.setItem(row, 0, number_item)
                name = QTableWidgetItem(("    " * int(param.get("indent") or 0)) + parameter_display_label(param))
                name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                name.setData(PARAM_ROLE, param.get("key"))
                name.setData(KIND_ROLE, "param")
                name.setBackground(row_bg)
                self.table.setItem(row, 1, name)
                designation = QTableWidgetItem(parameter_designation(param))
                designation.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                designation.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                designation.setBackground(row_bg)
                self.table.setItem(row, 2, designation)
                unit_item = QTableWidgetItem(format_unit(unit) if editable else "")
                unit_item.setData(UNIT_ROLE, unit)
                unit_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                unit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                unit_item.setBackground(row_bg)
                self.table.setItem(row, 3, unit_item)
                for col_index, column in enumerate(columns):
                    cell = self._cells.get(f"{param.get('key')}:{column.get('key')}")
                    text = (cell or {}).get("display") or (cell or {}).get("draft_value") or (cell or {}).get("value") or ""
                    item = QTableWidgetItem(str(text))
                    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    editable = (
                        param.get("row_kind") == "editable"
                        and not (cell or {}).get("locked")
                        and not (cell or {}).get("unified")
                        and not self._view_only()
                    )
                    if editable:
                        flags |= Qt.ItemFlag.ItemIsEditable
                    item.setFlags(flags)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setData(PARAM_ROLE, param.get("key"))
                    item.setData(COLUMN_ROLE, column.get("key"))
                    item.setData(OPTIONS_ROLE, (cell or {}).get("options") or param.get("options") or [])
                    item.setData(KIND_ROLE, "cell")
                    color = _status_color(
                        cell,
                        param.get("row_kind") or "editable",
                        show_changes=not (self.workbook or {}).get("is_issued"),
                    )
                    if color:
                        item.setBackground(QBrush(color))
                    self._decorate_cell_item(item, cell)
                    self.table.setItem(row, DATA_COLUMN + col_index, item)
            self.table.resizeColumnsToContents()
            header = self.table.horizontalHeader()
            header.resizeSection(0, self._number_column_width())
            header.resizeSection(1, self._parameter_column_width())
            header.resizeSection(2, self._designation_column_width())
            header.resizeSection(3, 80)
            stage_width = self._stage_column_width()
            for index, column in enumerate(columns):
                if column.get("kind") not in (None, "", "stage"):
                    continue
                header.resizeSection(DATA_COLUMN + index, stage_width)
            self.table.sync_frozen()
            self._hide_row_numbers()
            if self._selected:
                self._apply_highlight(*self._selected)
        finally:
            self.table.blockSignals(False)
            self._rebuilding = False

    def _keys_at(self, row: int, column: int) -> tuple[str, str] | None:
        item = self.table.item(row, column)
        if not item:
            return None
        param = item.data(PARAM_ROLE)
        col = item.data(COLUMN_ROLE)
        if param and col:
            return str(param), str(col)
        if param and column == 1:
            self.struct_label.setText(self.table.item(row, 1).text().strip() if self.table.item(row, 1) else "")
            unit_item = self.table.item(row, 3)
            raw_unit = unit_item.data(UNIT_ROLE) if unit_item is not None else ""
            self.struct_unit.setText("" if raw_unit is None else str(raw_unit))
            return None
        return None

    def _select_keys(self, parameter_key: str, column_key: str, emit: bool = True) -> None:
        self._selected = (parameter_key, column_key)
        self._apply_highlight(parameter_key, column_key)
        cell = self._cells.get(f"{parameter_key}:{column_key}") or {}
        self.link_edit.blockSignals(True)
        self.link_edit.setText(cell.get("hyperlink") or "")
        self.link_edit.blockSignals(False)
        self._show_cell_link(cell)
        param = next((item for item in (self.catalog or {}).get("parameters") or [] if item.get("key") == parameter_key), None)
        col = next((item for item in (self.catalog or {}).get("columns") or [] if item.get("key") == column_key), None)
        unit = format_unit((param or {}).get("unit") or "")
        label = parameter_display_label(param or {})
        self.cell_caption.setText(f"{label}{', ' + unit if unit else ''} / ступень {(col or {}).get('label') or ''}")
        self.history_empty.hide()
        editing = self.table_mode == "edit" and self.can_write and not self._view_only()
        self.edit_row.setVisible(editing)
        self.view_hint.setVisible(not editing)
        if cell.get("unified"):
            self.lock_hint.setText("Унификация включена. Изменение значения ячейки запрещено.")
            self.lock_hint.show()
        elif cell.get("locked"):
            self.lock_hint.setText("Поле автоматически заблокировано правилом унификации.")
            self.lock_hint.show()
        else:
            self.lock_hint.hide()
        self.discard_btn.setEnabled(cell.get("status") == "draft")
        if emit:
            self.cell_selected.emit(parameter_key, column_key)
            self.history_needed.emit(parameter_key, column_key)

    def _apply_highlight(self, parameter_key: str, column_key: str) -> None:
        catalog = self.catalog or {}
        parameters = self._shown_parameters
        columns = catalog.get("columns") or []
        sel_row = next((i for i, item in enumerate(parameters) if item.get("key") == parameter_key), -1)
        sel_col = next((i for i, item in enumerate(columns) if item.get("key") == column_key), -1)
        blocked = self.table.signalsBlocked()
        self.table.blockSignals(True)
        try:
            for row, param in enumerate(parameters):
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if not item:
                        continue
                    cell = None
                    if col >= DATA_COLUMN:
                        cell = self._cells.get(f"{param.get('key')}:{columns[col - DATA_COLUMN].get('key')}")
                    if col < DATA_COLUMN:
                        color = QColor(SECTION_BG if param.get("row_kind") != "editable" else PARAM_BG)
                    else:
                        color = _status_color(
                            cell,
                            param.get("row_kind") or "editable",
                            show_changes=not (self.workbook or {}).get("is_issued"),
                        )
                    if row == sel_row or (col >= DATA_COLUMN and col - DATA_COLUMN == sel_col):
                        if color is None:
                            color = QColor(HIGHLIGHT)
                    if color:
                        item.setBackground(QBrush(color))
                    else:
                        item.setBackground(QBrush())
                    selected = row == sel_row and col >= DATA_COLUMN and col - DATA_COLUMN == sel_col
                    if col >= DATA_COLUMN:
                        self._decorate_cell_item(item, cell, selected=selected)
                    else:
                        item.setForeground(QBrush(QColor("#263238")))
                    if col < DATA_COLUMN:
                        self.table.paint_frozen_item(row, col, item)
        finally:
            self.table.blockSignals(blocked)

    def _cell_entered(self, row: int, column: int) -> None:
        keys = self._keys_at(row, column)
        cell = self._cells.get(f"{keys[0]}:{keys[1]}") if keys else None
        hand = bool((cell or {}).get("hyperlink"))
        self.table.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if hand else Qt.CursorShape.ArrowCursor
        )
        if keys and keys != self._hover_keys:
            self._hover_keys = keys
            self.last_comment_needed.emit(*keys)

    def _cell_clicked(self, row: int, column: int) -> None:
        keys = self._keys_at(row, column)
        if keys and QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            cell = self._cells.get(f"{keys[0]}:{keys[1]}") or {}
            if cell.get("hyperlink"):
                self._open_hyperlink(str(cell["hyperlink"]))
                self._select_keys(*keys)
                return
        if not keys:
            parameters = self._shown_parameters
            if 0 <= row < len(parameters):
                self.struct_label.blockSignals(True)
                param = parameters[row]
                label = param.get("label") or ""
                unit = param.get("unit") or ""
                if unit and label.endswith(f", {unit}"):
                    label = label[: -len(unit) - 2].strip()
                self.struct_label.setText(label)
                self.struct_unit.setText(unit)
                indent = int(param.get("indent") or 1)
                self.struct_indent.setCurrentIndex(min(max(indent, 0), 2))
                self.struct_label.setProperty("param_key", param.get("key"))
                self.struct_label.blockSignals(False)
            return
        self._select_keys(*keys)

    def _cell_double(self, row: int, column: int) -> None:
        keys = self._keys_at(row, column)
        if keys:
            self._select_keys(*keys)
        if self.table_mode != "edit":
            return

    def _current_changed(self, row: int, column: int, _prev_row: int, _prev_col: int) -> None:
        keys = self._keys_at(row, column)
        if keys:
            self._select_keys(*keys)

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._rebuilding or self.table.signalsBlocked() or self.table_mode != "edit":
            return
        param = item.data(PARAM_ROLE)
        column = item.data(COLUMN_ROLE)
        if not param or not column:
            return
        current = self._cells.get(f"{param}:{column}") or {}
        text = item.text()
        previous = current.get("display") or current.get("draft_value") or current.get("value") or ""
        hyperlink = self.link_edit.text().strip() or None
        if text == previous and hyperlink == (current.get("hyperlink") or None):
            return
        self.draft_requested.emit(str(param), str(column), text, hyperlink)

    def _cell_value(self, parameter_key: str, column_key: str) -> str:
        cell = self._cells.get(f"{parameter_key}:{column_key}") or {}
        parameters = self._shown_parameters
        columns = (self.catalog or {}).get("columns") or []
        row = next((index for index, item in enumerate(parameters) if item.get("key") == parameter_key), -1)
        col = next((index for index, item in enumerate(columns) if item.get("key") == column_key), -1)
        item = self.table.item(row, DATA_COLUMN + col) if row >= 0 and col >= 0 else None
        if item:
            return item.text()
        return cell.get("display") or cell.get("draft_value") or cell.get("value") or ""

    def commit_editor(self) -> None:
        self._commit_editor()

    def _commit_editor(self) -> None:
        if self.table.state() == QAbstractItemView.State.EditingState:
            editor = self.table.focusWidget()
            self.table.setFocus()
            if editor is not None and editor is not self.table:
                editor.clearFocus()
            QApplication.processEvents()

    def _has_drafts(self) -> bool:
        if self.unsaved:
            return True
        return any((cell or {}).get("status") == "draft" for cell in self._cells.values())

    def _can_save_draft(self, parameter_key: str, column_key: str) -> bool:
        if not self.can_write or self._view_only():
            return False
        cell = self._cells.get(f"{parameter_key}:{column_key}") or {}
        if cell.get("locked") or cell.get("unified"):
            return False
        if cell.get("status") == "draft":
            return True
        if any(
            item.get("parameter_key") == parameter_key and item.get("column_key") == column_key
            for item in self.unsaved
        ):
            return True
        return self._cell_value(parameter_key, column_key) != (
            cell.get("display") or cell.get("draft_value") or cell.get("value") or ""
        )

    def _confirm(self) -> None:
        if not self._selected:
            return
        self._commit_editor()
        param, column = self._selected
        comment = self.comment_edit.text().strip() or self.cell_comment.toPlainText().strip()
        if not comment:
            self._start_draft_save(param, column)
            return
        self.confirm_requested.emit(
            param,
            column,
            self._cell_value(param, column),
            comment,
            self.link_edit.text().strip() or None,
        )
        self.comment_edit.clear()
        self.cell_comment.clear()
        self.comment_box.hide()
        self._draft_save_target = None

    def _discard(self) -> None:
        if self._selected:
            self.discard_requested.emit(*self._selected)

    def _unify(self) -> None:
        if not self._selected:
            return
        param, column = self._selected
        cell = self._cells.get(f"{param}:{column}") or {}
        self.unify_requested.emit(param, column, not bool(cell.get("unified")))

    def _toggle_structure(self) -> None:
        if not self.structure_edit:
            self._open_header_structure()
            return
        self.structure_edit = False
        self.structure_panel.hide()
        self._refresh_hints()

    def _param_key(self) -> str:
        return str(self.struct_label.property("param_key") or "")

    def _save_parameter(self) -> None:
        key = self._param_key()
        if not key:
            return
        indent = int(self.struct_indent.currentData())
        self.update_parameter_requested.emit(
            key,
            {
                "label": self.struct_label.text().strip(),
                "unit": self.struct_unit.text().strip(),
                "indent": indent,
                "row_kind": "section" if indent == 0 else "editable",
            },
        )

    def _add_parameter(self) -> None:
        indent = int(self.struct_indent.currentData())
        self.add_parameter_requested.emit(
            {
                "label": self.struct_label.text().strip() or "Новый параметр",
                "unit": self.struct_unit.text().strip(),
                "indent": indent,
                "row_kind": "section" if indent == 0 else "editable",
                "insert_after": self._param_key() or None,
            }
        )

    def _add_child(self) -> None:
        parent_key = self._param_key()
        parent = next((item for item in (self.catalog or {}).get("parameters") or [] if item.get("key") == parent_key), None)
        indent = min(int((parent or {}).get("indent") or 0) + 1, 2)
        self.add_parameter_requested.emit(
            {
                "label": self.struct_label.text().strip() or "Новый параметр",
                "unit": self.struct_unit.text().strip(),
                "indent": indent,
                "row_kind": "editable",
                "insert_after": parent_key or None,
                "group": (parent or {}).get("key"),
            }
        )

    def _delete_parameter(self) -> None:
        key = self._param_key()
        if key:
            self.delete_parameter_requested.emit(key)

    def _column_picked(self) -> None:
        key = self.column_combo.currentData()
        column = next((item for item in (self.catalog or {}).get("columns") or [] if item.get("key") == key), None)
        if column:
            self.column_label.setText(column.get("label") or "")

    def _save_column(self) -> None:
        key = self.column_combo.currentData()
        if key and self.column_label.text().strip():
            self.update_column_requested.emit(str(key), self.column_label.text().strip())

    def _delete_column(self) -> None:
        key = self.column_combo.currentData()
        if key:
            self.delete_column_requested.emit(str(key))

    def _add_column(self) -> None:
        label = self.new_column.text().strip()
        if label:
            self.add_column_requested.emit(label)
            self.new_column.clear()

    def _sheet_writable(self) -> bool:
        return bool(self.can_write and not self.busy and not self._view_only())

    def _column_key_at(self, logical_index: int) -> str | None:
        columns = (self.catalog or {}).get("columns") or []
        index = logical_index - DATA_COLUMN
        if 0 <= index < len(columns):
            return str(columns[index].get("key") or "") or None
        return None

    def _select_header_column(self, key: str) -> None:
        index = self.column_combo.findData(key)
        if index >= 0:
            self.column_combo.setCurrentIndex(index)
            self._column_picked()

    def _open_header_structure(self) -> None:
        if not self._sheet_writable():
            return
        self.set_mode("edit")
        self.structure_edit = True
        self.structure_panel.show()
        self._refresh_hints()

    def _header_clicked(self, index: int) -> None:
        key = self._column_key_at(index)
        if key:
            self._select_header_column(key)

    def _header_double_clicked(self, index: int) -> None:
        key = self._column_key_at(index)
        if key:
            self._rename_header_column(key)

    def _header_menu(self, index: int, global_pos) -> None:
        menu = QMenu(self)
        writable = self._sheet_writable()
        key = self._column_key_at(index)
        edit = menu.addAction("Редактировать структуру шапки", self._open_header_structure)
        edit.setEnabled(writable)
        if key:
            column = next((item for item in (self.catalog or {}).get("columns") or [] if item.get("key") == key), None)
            rename = menu.addAction(
                f"Переименовать «{(column or {}).get('label') or key}»…",
                lambda: self._rename_header_column(key),
            )
            rename.setEnabled(writable)
            delete = menu.addAction("Удалить столбец", lambda: self._delete_header_column(key))
            delete.setEnabled(writable)
        add = menu.addAction("Добавить столбец…", self._prompt_add_column)
        add.setEnabled(writable)
        self._add_clear_highlight_action(menu)
        menu.exec(global_pos)

    def _rename_header_column(self, key: str) -> None:
        if not self._sheet_writable():
            return
        column = next((item for item in (self.catalog or {}).get("columns") or [] if item.get("key") == key), None)
        text, ok = QInputDialog.getText(
            self,
            "Столбец шапки",
            "Наименование столбца",
            QLineEdit.EchoMode.Normal,
            (column or {}).get("label") or "",
        )
        if ok and text.strip():
            self.update_column_requested.emit(key, text.strip())

    def _prompt_add_column(self) -> None:
        if not self._sheet_writable():
            return
        text, ok = QInputDialog.getText(self, "Новый столбец", "Наименование столбца")
        if ok and text.strip():
            self.add_column_requested.emit(text.strip())

    def _delete_header_column(self, key: str) -> None:
        self._select_header_column(key)
        self.delete_column_requested.emit(key)

    def _decorate_cell_item(self, item: QTableWidgetItem, cell: dict | None, selected: bool = False) -> None:
        font = item.font()
        has_link = bool((cell or {}).get("hyperlink"))
        font.setUnderline(has_link)
        item.setFont(font)
        if selected or has_link:
            item.setForeground(QBrush(QColor(PRIMARY)))
        else:
            item.setForeground(QBrush(QColor("#263238")))
        url = str((cell or {}).get("hyperlink") or "").strip()
        item.setToolTip("Нажмите Ctrl+ЛКМ, чтобы открыть ссылку" if url else "")

    def _show_cell_link(self, cell: dict | None) -> None:
        url = str((cell or {}).get("hyperlink") or "").strip()
        if not url:
            self.link_view.hide()
            self.link_view.clear()
            return
        safe = escape(url, quote=True)
        self.link_view.setText(f'Ссылка: <a href="{safe}">{safe}</a>')
        self.link_view.show()

    def _save_link_draft(self) -> None:
        if not self._selected or self.table_mode != "edit" or not self._sheet_writable():
            return
        param, column = self._selected
        cell = self._cells.get(f"{param}:{column}") or {}
        hyperlink = self.link_edit.text().strip() or None
        if hyperlink == (cell.get("hyperlink") or None):
            return
        self.draft_requested.emit(param, column, self._cell_value(param, column), hyperlink)

    def _edit_hyperlink(self, parameter_key: str, column_key: str) -> None:
        if not self._sheet_writable():
            return
        self.set_mode("edit")
        self._select_keys(parameter_key, column_key)
        self._set_history_visible(True)
        cell = self._cells.get(f"{parameter_key}:{column_key}") or {}
        text, ok = QInputDialog.getText(
            self,
            "Ссылка в ячейке",
            "Ссылка на документ",
            QLineEdit.EchoMode.Normal,
            cell.get("hyperlink") or "",
        )
        if ok:
            self._set_hyperlink(parameter_key, column_key, text.strip() or None)

    def _set_hyperlink(self, parameter_key: str, column_key: str, hyperlink: str | None) -> None:
        self.draft_requested.emit(parameter_key, column_key, self._cell_value(parameter_key, column_key), hyperlink)

    def _open_hyperlink(self, url: str) -> None:
        target = (url or "").strip()
        if not target:
            return
        QDesktopServices.openUrl(QUrl.fromUserInput(target))

    def _sheet_changed(self, sheet_id: str) -> None:
        if sheet_id and sheet_id != (self.workbook or {}).get("id"):
            self.sheet_selected.emit(str(sheet_id))

    def _sheet_menu_at(self, sheet_id: str, global_pos) -> None:
        sheet = next((item for item in self.sheets if item.get("id") == sheet_id), None)
        if not sheet:
            return
        menu = QMenu(self)
        writable = self.can_write and not self.busy
        rename = menu.addAction("Переименовать лист", lambda: self.sheet_rename_requested.emit(sheet_id))
        rename.setEnabled(writable and not sheet.get("is_primary"))
        if not sheet.get("is_primary"):
            issued = menu.addAction(
                "Версия выдана",
                lambda _checked=False, sid=sheet_id: self.sheet_issued_requested.emit(sid),
            )
            issued.setCheckable(True)
            issued.setChecked(bool(sheet.get("is_issued")))
            issued.setEnabled(writable)
        if sheet.get("is_primary"):
            ordinary = menu.addAction("Сделать обычным листом", lambda: self.sheet_ordinary_requested.emit(sheet_id))
            ordinary.setEnabled(writable)
        else:
            primary = menu.addAction("Сделать основным", lambda: self.sheet_primary_requested.emit(sheet_id))
            primary.setEnabled(writable and not sheet.get("is_issued"))
        copy = menu.addAction("Копировать лист", lambda: self.sheet_copy_requested.emit(sheet_id))
        copy.setEnabled(writable)
        delete = menu.addAction("Удалить лист", lambda: self.sheet_delete_requested.emit(sheet_id))
        delete.setEnabled(writable and len(self.sheets) > 1)
        menu.exec(global_pos)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.table.viewport() and event.type() == QEvent.Type.Leave:
            self.table.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        if event.type() == QEvent.Type.ContextMenu and self.history_panel.isVisible():
            if watched in {self.history_table, self.history_table.viewport()}:
                return super().eventFilter(watched, event)
            if (watched is self.history_panel or self.history_panel.isAncestorOf(watched)) and not isinstance(
                watched, (QLineEdit, QPlainTextEdit)
            ):
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                self._exec_history_menu(global_pos)
                return True
        return super().eventFilter(watched, event)

    def _history_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Скрыть историю", lambda: self._set_history_visible(False))
        menu.addSeparator()
        heading = menu.addAction("Расположение панели")
        heading.setEnabled(False)
        right = menu.addAction("Справа", lambda: self.history_position_requested.emit("right"))
        bottom = menu.addAction("Снизу", lambda: self.history_position_requested.emit("bottom"))
        on_bottom = self._history_position == "bottom"
        right.setText("Справа" if on_bottom else "✓ Справа")
        bottom.setText("✓ Снизу" if on_bottom else "Снизу")
        return menu

    def _exec_history_menu(self, global_pos) -> None:
        self._history_context_menu().exec(global_pos)

    def _history_menu(self, pos) -> None:
        if not self.history_panel.isVisible():
            return
        sender = self.sender()
        origin = sender.mapToGlobal(pos) if sender is not None else self.history_panel.mapToGlobal(pos)
        self._exec_history_menu(origin)

    def _frozen_menu(self, global_pos) -> None:
        index = self.table.frozen.indexAt(self.table.frozen.viewport().mapFromGlobal(global_pos))
        self._show_table_menu(index.row(), index.column(), global_pos)

    def _cell_menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        row = item.row() if item else self.table.indexAt(pos).row()
        column = item.column() if item else self.table.indexAt(pos).column()
        self._show_table_menu(row, column, self.table.viewport().mapToGlobal(pos))

    def _show_table_menu(self, row: int, column: int, global_pos) -> None:
        keys = self._keys_at(row, column) if row >= 0 and column >= 0 else None
        menu = QMenu(self)
        if not keys:
            menu.addAction("Найти в таблице", self._open_find)
            if self.history_panel.isVisible():
                menu.addAction("Скрыть историю", lambda: self._set_history_visible(False))
            else:
                menu.addAction("Показать историю", lambda: self._set_history_visible(True))
            self._add_clear_highlight_action(menu)
            menu.exec(global_pos)
            return
        param, col_key = keys
        self._select_keys(param, col_key)
        cell = self._cells.get(f"{param}:{col_key}") or {}
        locked = bool(cell.get("locked") or cell.get("unified") or self._view_only())
        edit_act = menu.addAction("Изменить данные в ячейке", lambda: self._start_edit(param, col_key))
        edit_act.setEnabled(self.can_write and not locked and not self.busy)
        menu.addAction("Найти в таблице", self._open_find)
        if self.history_panel.isVisible():
            menu.addAction("Скрыть историю", lambda: self._set_history_visible(False))
        menu.addAction("Показать историю", lambda: self._show_history_for(param, col_key))
        unify = QAction("Снять унификацию" if cell.get("unified") else "Установить унификацию", self)
        unify.triggered.connect(self._unify)
        unify.setEnabled(self.can_write and not self._view_only() and not self.busy)
        menu.addAction(unify)
        link_label = "Изменить ссылку…" if cell.get("hyperlink") else "Добавить ссылку…"
        link_act = menu.addAction(link_label, lambda: self._edit_hyperlink(param, col_key))
        link_act.setEnabled(self.can_write and not locked and not self.busy)
        if cell.get("hyperlink"):
            menu.addAction("Открыть ссылку", lambda: self._open_hyperlink(str(cell.get("hyperlink"))))
            clear_link = menu.addAction("Удалить ссылку", lambda: self._set_hyperlink(param, col_key, None))
            clear_link.setEnabled(self.can_write and not locked and not self.busy)
        comment_act = menu.addAction("Оставить комментарий", self._open_comment)
        comment_act.setEnabled(self.can_write and not cell.get("locked") and not self._view_only())
        save_act = menu.addAction("Сохранить черновик", lambda: self._start_draft_save(param, col_key))
        save_act.setEnabled(self._can_save_draft(param, col_key) and not self.busy)
        all_act = menu.addAction("Сохранить все черновики", lambda: self.save_all_drafts_requested.emit())
        all_act.setEnabled(self._has_drafts() and self.can_write)
        self._add_clear_highlight_action(menu)
        menu.exec(global_pos)

    def _show_history_for(self, parameter_key: str, column_key: str) -> None:
        self._set_history_visible(True)
        self._select_keys(parameter_key, column_key)

    def _start_edit(self, parameter_key: str, column_key: str) -> None:
        self.set_mode("edit")
        self._select_keys(parameter_key, column_key)
        row = self.table.currentRow()
        col = self.table.currentColumn()
        if row >= 0 and col >= DATA_COLUMN:
            self.table.editItem(self.table.item(row, col))

    def _open_comment(self) -> None:
        self._draft_save_target = None
        self._set_history_visible(True)
        self.comment_label.setText("Комментарий к ячейке")
        self.add_comment_btn.setText("Добавить комментарий")
        self.comment_box.show()
        self.cell_comment.setFocus()

    def _start_draft_save(self, parameter_key: str, column_key: str) -> None:
        self._commit_editor()
        self.set_mode("edit")
        self._select_keys(parameter_key, column_key)
        self._draft_save_target = (parameter_key, column_key)
        self._set_history_visible(True)
        self.comment_label.setText("Комментарий для сохранения черновика")
        self.add_comment_btn.setText("Сохранить черновик")
        self.comment_box.show()
        self.cell_comment.clear()
        self.cell_comment.setFocus()

    def _cancel_comment(self) -> None:
        self._draft_save_target = None
        self.cell_comment.clear()
        self.comment_box.hide()
        self.add_comment_btn.setText("Добавить комментарий")

    def _submit_comment(self) -> None:
        text = self.cell_comment.toPlainText().strip()
        if not text:
            self.cell_comment.setFocus()
            return
        if self._draft_save_target:
            param, column = self._draft_save_target
            self.confirm_requested.emit(
                param,
                column,
                self._cell_value(param, column),
                text,
                self.link_edit.text().strip() or None,
            )
            self._cancel_comment()
            self.comment_edit.clear()
            return
        if not self._selected:
            return
        self.comment_requested.emit(*self._selected, text)
        self._cancel_comment()

    def _open_find(self) -> None:
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _find(self, text: str) -> None:
        needle = text.strip().casefold()
        self._find_hits = []
        if needle:
            for row in range(self.table.rowCount()):
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item and needle in item.text().casefold():
                        self._find_hits.append((row, col))
        self._find_index = 0
        self.find_count.setText(f"{len(self._find_hits)} совп." if self._find_hits else "")
        if self._find_hits:
            row, col = self._find_hits[0]
            self.table.setCurrentCell(row, col)

    def _step_find(self, delta: int) -> None:
        if not self._find_hits:
            return
        self._find_index = (self._find_index + delta) % len(self._find_hits)
        row, col = self._find_hits[self._find_index]
        self.table.setCurrentCell(row, col)
