from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QBitmap, QColor, QPainter, QPalette, QRegion
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

INDEPENDENT_WINDOW_FLAGS = (
    Qt.WindowType.Window
    | Qt.WindowType.CustomizeWindowHint
    | Qt.WindowType.WindowTitleHint
    | Qt.WindowType.WindowSystemMenuHint
    | Qt.WindowType.WindowMinimizeButtonHint
    | Qt.WindowType.WindowMaximizeButtonHint
    | Qt.WindowType.WindowCloseButtonHint
)


def configure_independent_window(widget: QWidget) -> None:
    """Отдельное окно: свернуть, развернуть и закрыть, как у основного приложения."""
    widget.setWindowFlags(INDEPENDENT_WINDOW_FLAGS)
    widget.setWindowModality(Qt.WindowModality.NonModal)
    if isinstance(widget, QDialog):
        widget.setSizeGripEnabled(True)

APP_QSS = """
QMainWindow, QDialog, QWidget {
  background: #f7f9fd;
  color: #263238;
  font-family: "Segoe UI", Tahoma, sans-serif;
  font-size: 13px;
}
QMainWindow { border: none; }
QStatusBar { background: #f7f9fd; border: none; }

QPushButton {
  background: #dceeff;
  border: 1px solid #c3d8f2;
  border-radius: 8px;
  padding: 8px 12px;
  color: #263238;
  min-height: 22px;
}
QPushButton:hover:!disabled {
  background: #cfe6ff;
  border-color: #b9cde8;
}
QPushButton:pressed:!disabled { padding-top: 9px; padding-bottom: 7px; }
QPushButton:disabled { color: #90a4b8; }
QPushButton[flatMenu="true"] {
  background: transparent;
  border: none;
  border-radius: 8px;
  padding: 7px 12px;
}
QPushButton[flatMenu="true"]:hover { background: #f3f7fc; }
QPushButton[flatMenu="true"]:checked { background: #f3f7fc; }
QPushButton[flatMenu="true"][alert="true"] {
  color: #b42318;
  font-weight: 700;
}
QPushButton[flatMenu="true"][alert="true"][pulse="true"] {
  background: #fdecea;
}
QPushButton[flatMenu="true"][alert="true"]:hover {
  color: #b42318;
  background: #f8d5d2;
}
QWidget#tab-host {
  background: transparent;
}
QWidget#guide-tabs {
  background: transparent;
  border: none;
}
QPushButton[tab="true"] {
  background: #edf4fb;
  border: 1px solid #d9e3f0;
  border-bottom: 1px solid #d9e3f0;
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  padding: 8px 16px;
  margin-top: 3px;
  min-height: 18px;
  font-weight: 400;
  outline: none;
}
QPushButton[tab="true"]:hover:!checked:!disabled {
  background: #f7fbff;
  border-color: #d9e3f0;
}
QPushButton[tab="true"]:pressed:!disabled {
  padding: 8px 16px;
  background: #edf4fb;
}
QPushButton[tab="true"]:checked,
QPushButton[tab="true"]:checked:hover,
QPushButton[tab="true"]:checked:pressed {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-bottom: 1px solid #ffffff;
  margin-top: 0;
  margin-bottom: -1px;
  padding: 10px 16px 9px 16px;
  font-weight: 600;
}
QPushButton[tab="true"]:disabled {
  color: #8a9aaa;
  background: #f3f6fa;
}
QPushButton[tab="true"]:focus {
  outline: none;
}
QPushButton[sheetTab="true"] {
  background: #f3f7fc;
  border: 1px solid #d9e3f0;
  border-bottom: 1px solid #d9e3f0;
  border-radius: 8px 8px 0 0;
  padding: 7px 14px;
  margin-bottom: -1px;
}
QPushButton[sheetTab="true"]:checked {
  background: #ffffff;
  border-color: #d9e3f0;
  border-bottom-color: #ffffff;
  font-weight: 600;
}
QPushButton[sheetTab="true"][mainSheet="true"] {
  background: #1d6fd0;
  color: #ffffff;
  border-color: #1558a8;
}
QPushButton[sheetTab="true"][mainSheet="true"]:checked {
  background: #1558a8;
  color: #ffffff;
  border-color: #0f4a91;
  border-bottom-color: #1558a8;
  font-weight: 600;
}
QPushButton[sheetTab="true"][mainSheet="true"]:disabled {
  background: #7aa7d9;
  color: #eef5fc;
  border-color: #6b98c8;
}
QPushButton[sheetTab="true"][baseSheet="true"] {
  background: #6b7380;
  color: #ffffff;
  border-color: #565e6a;
}
QPushButton[sheetTab="true"][baseSheet="true"]:checked {
  background: #565e6a;
  color: #ffffff;
  border-color: #454c56;
  border-bottom-color: #565e6a;
  font-weight: 600;
}
QPushButton[sheetTab="true"][baseSheet="true"]:disabled {
  background: #9aa2ad;
  color: #f3f4f6;
  border-color: #8a929c;
}
QFrame#sheet-tabs {
  background: transparent;
  border: none;
  border-bottom: 1px solid #d9e3f0;
}
QToolButton#sheet-versions-toggle {
  background: transparent;
  color: #9aabb8;
  border: none;
  padding: 2px 0;
  margin: 0;
  min-width: 16px;
  max-width: 16px;
}
QToolButton#sheet-versions-toggle:hover {
  background: transparent;
  color: #6b7c8a;
}
QToolButton#sheet-versions-toggle:disabled {
  background: transparent;
  color: #c5d0d8;
}
QTableWidget#id-sheet {
  border-radius: 0;
}
QTableWidget#id-sheet-frozen {
  background: #f7f9fd;
  border: none;
  border-right: 1px solid #d9e3f0;
  border-radius: 0;
}
QFrame#triangle-subtabs {
  background: transparent;
  border: none;
  border-bottom: 1px solid #d9e3f0;
}
QFrame#parameter-tree-combo {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
}
QFrame#parameter-tree-combo QLabel {
  background: transparent;
  color: #263238;
  padding: 6px 4px 6px 10px;
}
QFrame#parameter-tree-combo:disabled {
  background: #f3f6fa;
}
QFrame#parameter-tree-combo:disabled QLabel {
  color: #8a9aaa;
}
QFrame#triangle-toolbar {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
}
QTableWidget#triangle-grid,
QTableWidget#triangle-grid-header {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  gridline-color: #d9e3f0;
}
QTableWidget#triangle-grid-header {
  border-bottom: none;
}
QTableWidget#triangle-stage-column {
  background: #ffffff;
  border: none;
  border-right: 1px solid #d9e3f0;
  border-radius: 0;
}
QTableWidget#triangle-grid {
  border-top: none;
}
QTableWidget#triangle-grid QHeaderView::section,
QTableWidget#triangle-grid-header QHeaderView::section {
  background: #eef5fb;
  color: #68798b;
  border: 1px solid #d9e3f0;
  padding: 4px 0;
  font-size: 12px;
}
QTableWidget#report-sheet {
  background: #ffffff;
  gridline-color: #d9e3f0;
}
QPushButton[modeBtn="true"] {
  width: 38px;
  max-width: 38px;
  min-width: 38px;
  height: 34px;
  padding: 5px;
  background: #edf4fb;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
}
QPushButton[modeBtn="true"]:checked {
  background: #dbeafe;
  border-color: #c3d8f2;
}
QPushButton[circle="true"] {
  min-width: 28px;
  max-width: 28px;
  width: 28px;
  height: 24px;
  padding: 0;
  border-radius: 14px;
  background: transparent;
  border: none;
}
QPushButton[circle="true"]:hover { background: #f3f7fc; }
QPushButton[circle="true"]:disabled { color: #aaa; }
QPushButton[historyNav="true"] {
  min-width: 34px;
  max-width: 34px;
  width: 34px;
  height: 28px;
  padding: 2px;
  border-radius: 8px;
  background: transparent;
  border: 1px solid transparent;
}
QPushButton[historyNav="true"]:hover:!disabled {
  background: #f3f7fc;
  border-color: #d9e3f0;
}
QPushButton[historyNav="true"]:pressed:!disabled {
  background: #dbeafe;
  padding: 2px;
}
QPushButton[historyNav="true"]:disabled {
  background: transparent;
  border-color: transparent;
}
QPushButton[included="true"] {
  width: 22px; max-width: 22px; min-width: 22px; height: 22px; padding: 0;
  border-radius: 6px; font-weight: 700;
  border: 1px solid #27934a; background: #62d987; color: #174d2b;
}
QPushButton[included="false"] {
  width: 22px; max-width: 22px; min-width: 22px; height: 22px; padding: 0;
  border-radius: 6px; font-weight: 700;
  border: 1px solid #dfe4eb; background: #f3f5f8; color: #748094;
}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
  padding: 8px 10px;
  color: #263238;
  min-height: 22px;
  selection-background-color: #dbeafe;
  selection-color: #263238;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
  border-color: #b9cde8;
}
QComboBox::drop-down {
  subcontrol-origin: padding;
  subcontrol-position: center right;
  width: 22px;
  border: none;
  background: transparent;
}
QComboBox::down-arrow, QComboBox::down-arrow:on {
  image: url(__CHEVRON__);
  width: 12px;
  height: 8px;
}
QComboBox QLineEdit {
  border: none;
  background: #ffffff;
  color: #263238;
  padding: 0 4px;
  min-height: 0;
  selection-background-color: #dbeafe;
  selection-color: #263238;
}
QComboBox QAbstractItemView {
  background: #ffffff;
  color: #263238;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
  padding: 4px;
  outline: none;
}
QComboBox QAbstractItemView::item {
  border-radius: 6px;
  padding: 4px 8px;
  min-height: 22px;
}
QComboBox QAbstractItemView::item:selected {
  background: #dbeafe;
  color: #263238;
}

QTableWidget, QTableView {
  background: #ffffff;
  gridline-color: #d9e3f0;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
  selection-background-color: transparent;
  selection-color: #263238;
  font-size: 12px;
}
QHeaderView::section {
  background: #eef5fb;
  color: #263238;
  border: 1px solid #d9e3f0;
  padding: 2px 6px;
  font-weight: 600;
  font-size: 12px;
}
QLabel#table-caption {
  font-size: 15px;
  font-weight: 600;
  color: #1f5e93;
  padding: 0 12px 6px;
  background: transparent;
}
QTableWidget#guide-table QHeaderView::section:vertical,
QTableWidget#id-sheet-frozen QHeaderView::section:vertical {
  width: 0px;
  max-width: 0px;
  min-width: 0px;
  padding: 0;
  border: none;
}
QTableWidget::item:selected {
  border: 2px solid #1565c0;
}

QListWidget, QTreeWidget {
  background: #ffffff;
  color: #263238;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
}
QListWidget::item {
  padding: 8px 10px;
  color: #263238;
}
QListWidget::item:hover {
  background: #e8f3ff;
  color: #263238;
}
QListWidget::item:selected,
QListWidget::item:selected:active,
QListWidget::item:selected:!active {
  background: #cfe6ff;
  color: #263238;
}
QFrame#object-suggestions {
  background: #ffffff;
  border: 1px solid #c3d8f2;
  border-radius: 8px;
}
QFrame#object-suggestions QListWidget {
  border: none;
  border-radius: 8px;
  color: #263238;
  outline: none;
}
QFrame#object-suggestions QListWidget::item {
  color: #263238;
}

QMenu {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-radius: 12px;
  padding: 5px;
}
QMenu::item {
  padding: 8px 12px;
  border-radius: 8px;
}
QMenu::item:selected { background: #dbeafe; }
QMenu::separator { height: 1px; background: #d9e3f0; margin: 4px 8px; }
QMenu::item:disabled { color: #8a9aaa; }

QScrollBar:vertical { background: #f4f7fb; width: 10px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: #c9d9ea; border-radius: 4px; min-height: 24px; }
QScrollBar:horizontal { background: #f4f7fb; height: 10px; margin: 0; border: none; }
QScrollBar::handle:horizontal { background: #c9d9ea; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QHeaderView { border: none; }
QHeaderView QScrollBar:horizontal { height: 0; max-height: 0; border: none; background: transparent; }
QHeaderView QScrollBar:vertical { width: 0; max-width: 0; border: none; background: transparent; }

QLabel[role="hint"] { color: #666; font-size: 12px; }
QLabel[role="ok"] {
  background: #dff0d8;
  border: 1px solid #b9d8b0;
  border-radius: 8px;
  padding: 10px 12px;
  color: #1b7a3d;
}
QLabel[role="warn"] {
  background: #fff3cd;
  border: 1px solid #ead59b;
  border-radius: 8px;
  padding: 10px 12px;
  color: #6b5300;
}
QLabel[role="error"] {
  background: #fff3cd;
  border: 1px solid #ead59b;
  border-radius: 8px;
  padding: 10px 12px;
  color: #b42318;
}
QLabel[role="user"] { color: #68798b; padding: 7px 12px; }
QFrame[card="true"],
QFrame#workspace-card {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-top-left-radius: 0;
  border-top-right-radius: 12px;
  border-bottom-left-radius: 12px;
  border-bottom-right-radius: 12px;
}
QFrame[menubar="true"] {
  background: #ffffff;
  border: none;
  border-bottom: 1px solid #d9e3f0;
}
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 7px; border-left: 1px solid #d9e3f0; border-right: 1px solid #d9e3f0; }
QSplitter::handle:vertical { height: 7px; border-top: 1px solid #d9e3f0; border-bottom: 1px solid #d9e3f0; }
QSplitter::handle:hover { background: rgba(31, 94, 147, 0.12); }
QToolTip {
  background: #ffffff;
  color: #263238;
  border: 1px solid #1f5e93;
  border-radius: 4px;
  padding: 7px 10px;
  font-size: 12px;
}
""".replace("__CHEVRON__", (Path(__file__).resolve().parent / "chevron-down.png").as_posix())

PRIMARY = "#1f5e93"
BG = "#f7f9fd"
SURFACE = "#ffffff"
DRAFT = "#fff59d"
CONFIRMED = "#c8e6c9"
IMPORTED = "#ffcc80"
COMPUTED = "#e0e0e0"
TRIANGLE = "#bbdefb"
HIGHLIGHT = "#f0f6fc"
SELECTED = "#1565c0"
UNIFIED = "#e0e0e0"
PARAM_BG = "#f7f9fd"
SECTION_BG = "#e8f1fb"
HEADER_BG = "#eef5fb"


class _RoundedPopupFilter(QObject):
    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() not in (QEvent.Type.Show, QEvent.Type.Resize):
            return False
        if not isinstance(watched, QWidget) or not watched.isWindow():
            return False
        name = watched.metaObject().className()
        is_combo = name == "QComboBoxPrivateContainer"
        is_completer = name == "QListView" and bool(watched.windowFlags() & Qt.WindowType.Popup)
        if not is_combo and not is_completer:
            return False
        if event.type() == QEvent.Type.Show and not watched.property("_rounded_popup"):
            watched.setProperty("_rounded_popup", True)
            if is_completer:
                _paint_popup_white(watched)
        _round_popup(watched)
        return False


def _paint_popup_white(popup: QWidget) -> None:
    white = QColor("#ffffff")
    ink = QColor("#263238")
    palette = popup.palette()
    palette.setColor(QPalette.ColorRole.Base, white)
    palette.setColor(QPalette.ColorRole.Window, white)
    palette.setColor(QPalette.ColorRole.Text, ink)
    popup.setPalette(palette)
    popup.setAutoFillBackground(True)
    viewport = getattr(popup, "viewport", None)
    if callable(viewport):
        view = viewport()
        view.setPalette(palette)
        view.setAutoFillBackground(True)
    popup.setStyleSheet(
        "QListView { background: #ffffff; color: #263238; border: 1px solid #d9e3f0;"
        " border-radius: 8px; outline: none; padding: 4px; }"
        "QListView::item { background: #ffffff; color: #263238; border-radius: 6px; padding: 4px 8px; }"
        "QListView::item:selected { background: #dbeafe; color: #263238; }"
    )


def _round_popup(widget: QWidget, radius: int = 8) -> None:
    if widget.width() < 8 or widget.height() < 8:
        return
    bitmap = QBitmap(widget.size())
    bitmap.fill(Qt.GlobalColor.color0)
    painter = QPainter(bitmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.color1)
    painter.drawRoundedRect(0, 0, widget.width(), widget.height(), radius, radius)
    painter.end()
    widget.setMask(QRegion(bitmap))


def install_rounded_popups(app: QApplication) -> None:
    if getattr(app, "_rounded_popups", None) is not None:
        return
    filt = _RoundedPopupFilter(app)
    app._rounded_popups = filt
    app.installEventFilter(filt)
