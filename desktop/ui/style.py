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
QPushButton[tab="true"] {
  background: #edf4fb;
  border: 1px solid #d9e3f0;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  padding: 8px 16px;
}
QPushButton[tab="true"]:checked {
  background: #ffffff;
  font-weight: 600;
}
QPushButton[tab="true"]:disabled { color: #8a9aaa; }
QPushButton[sheetTab="true"] {
  background: #f3f7fc;
  border: 1px solid #d9e3f0;
  border-radius: 8px 8px 0 0;
  padding: 7px 14px;
}
QPushButton[sheetTab="true"]:checked {
  background: #ffffff;
  border-color: #c3d8f2;
  font-weight: 600;
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
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
  border-color: #b9cde8;
}
QComboBox::drop-down { border: none; width: 18px; }

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
QTableWidget::item:selected {
  border: 2px solid #1565c0;
}

QListWidget, QTreeWidget {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-radius: 8px;
}
QListWidget::item { padding: 8px 10px; }
QListWidget::item:selected, QListWidget::item:hover { background: #cfe6ff; }

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

QScrollBar:vertical { background: #f4f7fb; width: 10px; }
QScrollBar::handle:vertical { background: #c9d9ea; border-radius: 4px; min-height: 24px; }
QScrollBar:horizontal { background: #f4f7fb; height: 10px; }
QScrollBar::handle:horizontal { background: #c9d9ea; border-radius: 4px; min-width: 24px; }

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
QFrame[card="true"] {
  background: #ffffff;
  border: 1px solid #d9e3f0;
  border-radius: 12px;
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
"""

PRIMARY = "#1f5e93"
BG = "#f7f9fd"
SURFACE = "#ffffff"
DRAFT = "#fff59d"
CONFIRMED = "#c8e6c9"
COMPUTED = "#e0e0e0"
TRIANGLE = "#bbdefb"
HIGHLIGHT = "#f0f6fc"
SELECTED = "#1565c0"
UNIFIED = "#e0e0e0"
PARAM_BG = "#f7f9fd"
SECTION_BG = "#e8f1fb"
HEADER_BG = "#eef5fb"
