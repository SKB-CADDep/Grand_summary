from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QRegion
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHeaderView,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.style import configure_independent_window


class GuideChoiceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, table_ready: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Обучение")
        self.kind = "app"
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        title = QLabel("Обучение")
        title.setStyleSheet("background: #1f5e93; color: white; font-weight: 600; padding: 14px 18px;")
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(title)
        body = QLabel(
            "Обзор приложения можно пройти сразу: вкладки, объект и треугольники.\n"
            "Работа с таблицей открывается только на вкладке «Таблица ИД», когда объект уже выбран."
        )
        body.setWordWrap(True)
        body.setStyleSheet("padding: 16px 18px;")
        layout.addWidget(body)
        row = QHBoxLayout()
        row.setContentsMargins(16, 0, 16, 8)
        app_btn = QPushButton("Обзор приложения")
        table_btn = QPushButton("Работа с таблицей")
        close_btn = QPushButton("Закрыть")
        table_btn.setEnabled(table_ready)
        if not table_ready:
            table_btn.setToolTip("Выберите объект и откройте вкладку «Таблица ИД».")
        app_btn.clicked.connect(lambda: self._pick("app"))
        table_btn.clicked.connect(lambda: self._pick("table"))
        close_btn.clicked.connect(self.reject)
        row.addWidget(app_btn)
        row.addWidget(table_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)
        if not table_ready:
            hint = QLabel("Сейчас «Работа с таблицей» недоступна: нужен выбранный объект и вкладка «Таблица ИД».")
            hint.setWordWrap(True)
            hint.setProperty("role", "hint")
            hint.setStyleSheet("padding: 0 18px 16px 18px;")
            layout.addWidget(hint)

    def _pick(self, kind: str) -> None:
        self.kind = kind
        self.accept()


class GuideOverlay(QWidget):
    finished = pyqtSignal()

    def __init__(self, steps: list[dict], host: QWidget, on_step) -> None:
        super().__init__(host)
        self._steps = steps
        self._index = 0
        self._host = host
        self._on_step = on_step
        self._hole = QRect()
        self._placing = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setGeometry(host.rect())
        self.raise_()
        self.card = QFrame(self)
        self.card.setObjectName("guide-card")
        self.card.setStyleSheet(
            "QFrame#guide-card { background: #ffffff; border: 1px solid #d9e3f0; border-radius: 12px; }"
            "QFrame#guide-card QLabel { background: transparent; border: none; }"
        )
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 12)
        card_layout.setSpacing(8)
        self.progress = QLabel()
        self.progress.setStyleSheet("color: #607d8b; font-size: 12px;")
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 700; font-size: 16px; color: #1a365d;")
        self.title.setWordWrap(True)
        self.lead = QLabel()
        self.lead.setWordWrap(True)
        self.lead.setStyleSheet("color: #37474f; font-size: 13px;")
        self.points_box = QWidget()
        self.points_layout = QVBoxLayout(self.points_box)
        self.points_layout.setContentsMargins(0, 2, 0, 2)
        self.points_layout.setSpacing(8)
        card_layout.addWidget(self.progress)
        card_layout.addWidget(self.title)
        card_layout.addWidget(self.lead)
        card_layout.addWidget(self.points_box)
        row = QHBoxLayout()
        self.back_btn = QPushButton("Назад")
        self.next_btn = QPushButton("Далее")
        skip = QPushButton("Пропустить обучение")
        skip.setFlat(True)
        skip.setStyleSheet("color: #1565c0; border: none; background: none; text-align: left; padding: 0;")
        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        skip.clicked.connect(self._skip)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        row.addWidget(self.next_btn)
        card_layout.addLayout(row)
        card_layout.addWidget(skip)
        self.card.setFixedWidth(460)
        self._render()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        dim = QColor(20, 32, 48, 130)
        if self._hole.isNull():
            painter.fillRect(self.rect(), dim)
            return
        hole = self._hole.adjusted(-4, -4, 4, 4)
        full = self.rect()
        painter.fillRect(QRect(0, 0, full.width(), max(0, hole.top())), dim)
        painter.fillRect(QRect(0, hole.bottom() + 1, full.width(), max(0, full.height() - hole.bottom() - 1)), dim)
        painter.fillRect(QRect(0, hole.top(), max(0, hole.left()), hole.height()), dim)
        painter.fillRect(
            QRect(hole.right() + 1, hole.top(), max(0, full.width() - hole.right() - 1), hole.height()),
            dim,
        )
        painter.setPen(QPen(QColor("#1565c0"), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(hole.adjusted(-2, -2, 2, 2))

    def _target(self) -> QWidget | None:
        name = self._steps[self._index].get("target")
        if not name:
            return None
        widget = self._host.findChild(QWidget, name)
        if widget is None or not widget.isVisible():
            return None
        return widget

    def _points(self, step: dict) -> list[str]:
        points = [str(item).strip() for item in (step.get("points") or []) if str(item).strip()]
        if points:
            return points
        body = str(step.get("body") or "").strip()
        return [body] if body else []

    def _fill_points(self, lines: list[str]) -> None:
        while self.points_layout.count():
            item = self.points_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for line in lines:
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            mark = QLabel("●")
            mark.setStyleSheet("color: #1565c0; font-size: 9px;")
            mark.setFixedWidth(12)
            mark.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            text = QLabel(line)
            text.setWordWrap(True)
            text.setFixedWidth(400)
            text.setStyleSheet("color: #263238; font-size: 13px;")
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            self.points_layout.addWidget(host)

    def _render(self) -> None:
        step = self._steps[self._index]
        if self._on_step:
            self._on_step(step)
        self.progress.setText(f"Шаг {self._index + 1} из {len(self._steps)}")
        self.title.setText(step.get("title") or "")
        lead = str(step.get("lead") or "").strip()
        self.lead.setText(lead)
        self.lead.setVisible(bool(lead))
        self._fill_points(self._points(step))
        self.back_btn.setEnabled(self._index > 0)
        self.next_btn.setText("Готово" if self._index == len(self._steps) - 1 else "Далее")
        self.card.adjustSize()
        self._place()
        self.update()
        QTimer.singleShot(0, self._place)

    def _place(self) -> None:
        if self._placing:
            return
        self._placing = True
        try:
            self._place_now()
        finally:
            self._placing = False

    def _place_now(self) -> None:
        target = self._target()
        if target is not None:
            origin = self.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
            self._hole = QRect(origin, target.size()).intersected(self.rect())
            if self._hole.width() < 2 or self._hole.height() < 2:
                self._hole = QRect()
        else:
            self._hole = QRect()
        self._move_card()
        self._cut_hole()
        self.card.raise_()
        self.raise_()
        self.update()

    def _move_card(self) -> None:
        self.card.adjustSize()
        card = QSize(self.card.width(), max(self.card.height(), 1))
        margin, gap = 12, 16
        bounds = self.rect().adjusted(margin, margin, -margin, -margin)
        hole = self._hole
        spots = [QPoint(margin, 48)]
        if not hole.isNull():
            spots = [
                QPoint(hole.right() + gap, hole.top()),
                QPoint(hole.left() - gap - card.width(), hole.top()),
                QPoint(hole.left(), hole.bottom() + gap),
                QPoint(hole.right() - card.width(), hole.bottom() + gap),
                QPoint(hole.left(), hole.top() - gap - card.height()),
            ]
        for spot in spots:
            rect = QRect(spot, card)
            if rect.right() > bounds.right():
                rect.moveRight(bounds.right())
            if rect.left() < bounds.left():
                rect.moveLeft(bounds.left())
            if rect.bottom() > bounds.bottom():
                rect.moveBottom(bounds.bottom())
            if rect.top() < bounds.top():
                rect.moveTop(bounds.top())
            if hole.isNull() or not rect.intersects(hole.adjusted(-8, -8, 8, 8)):
                self.card.move(rect.topLeft())
                return
        self.card.move(max(bounds.left(), bounds.right() - card.width()), max(bounds.top(), bounds.bottom() - card.height()))

    def _cut_hole(self) -> None:
        if self._hole.isNull() or self.width() < 2 or self.height() < 2:
            self.clearMask()
            return
        opening = self._hole.adjusted(-4, -4, 4, 4).intersected(self.rect())
        if opening.width() < 2 or opening.height() < 2:
            self.clearMask()
            return
        card = self.card.geometry().adjusted(-4, -4, 4, 4).intersected(self.rect().adjusted(-8, -8, 8, 8))
        region = QRegion(self.rect()).subtracted(QRegion(opening))
        if card.width() > 1 and card.height() > 1:
            region = region.united(QRegion(card))
        if region.isEmpty():
            self.clearMask()
            return
        self.setMask(region)

    def _back(self) -> None:
        self._index = max(0, self._index - 1)
        self._render()

    def _next(self) -> None:
        if self._index >= len(self._steps) - 1:
            self._skip()
            return
        self._index += 1
        self._render()

    def _skip(self) -> None:
        self.hide()
        self.finished.emit()
        self.deleteLater()


class GuideDialog(QDialog):
    """Сохранён для совместимости; обучение идёт через GuideOverlay."""
    def __init__(self, steps: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Обучение")
        self.resize(420, 280)
        self._steps = steps
        self._index = 0
        layout = QVBoxLayout(self)
        self.progress = QLabel()
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 15px;")
        self.body = QLabel()
        self.body.setWordWrap(True)
        layout.addWidget(self.progress)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addStretch(1)
        row = QHBoxLayout()
        self.back_btn = QPushButton("Назад")
        self.next_btn = QPushButton("Далее")
        self.skip_btn = QPushButton("Пропустить")
        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        self.skip_btn.clicked.connect(self.accept)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        row.addWidget(self.skip_btn)
        row.addWidget(self.next_btn)
        layout.addLayout(row)
        self._render()

    def _render(self) -> None:
        step = self._steps[self._index]
        self.progress.setText(f"Шаг {self._index + 1} из {len(self._steps)}")
        self.title.setText(step.get("title") or "")
        points = [str(item).strip() for item in (step.get("points") or []) if str(item).strip()]
        self.body.setText("\n".join(f"• {item}" for item in points) if points else (step.get("body") or ""))
        self.back_btn.setEnabled(self._index > 0)
        self.next_btn.setText("Готово" if self._index == len(self._steps) - 1 else "Далее")

    def _back(self) -> None:
        self._index = max(0, self._index - 1)
        self._render()

    def _next(self) -> None:
        if self._index >= len(self._steps) - 1:
            self.accept()
            return
        self._index += 1
        self._render()


class ChangelogDialog(QDialog):
    def __init__(self, releases: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Журнал изменений приложения")
        configure_independent_window(self)
        self.resize(820, 560)
        self._releases = releases
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Фильтр по версии, дате или тексту…")
        self.group = QComboBox()
        self.group.addItem("По дате", "date")
        self.group.addItem("По действиям", "action")
        self.query.textChanged.connect(self._rebuild)
        self.group.currentIndexChanged.connect(self._rebuild)
        toolbar.addWidget(self.query)
        toolbar.addWidget(QLabel("Группировка"))
        toolbar.addWidget(self.group)
        layout.addLayout(toolbar)
        split = QSplitter()
        self.tree = QListWidget()
        self.body = QTextBrowser()
        self.tree.currentRowChanged.connect(self._show)
        split.addWidget(self.tree)
        split.addWidget(self.body)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._filtered: list[dict] = []
        self._rebuild()

    def _rebuild(self) -> None:
        needle = self.query.text().strip().casefold()
        self._filtered = [
            item
            for item in self._releases
            if not needle
            or needle in f"{item.get('version')} {item.get('date')} {item.get('title')} {' '.join(item.get('items') or [])}".casefold()
        ]
        self.tree.clear()
        group_by = self.group.currentData()
        last_group = None
        for item in self._filtered:
            key = item.get("date") if group_by == "date" else item.get("title")
            if key != last_group:
                header = QListWidgetItem(str(key or ""))
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.tree.addItem(header)
                last_group = key
            label = f"v{item.get('version')}" if group_by == "date" else f"v{item.get('version')} — {item.get('date')}"
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, item)
            self.tree.addItem(row)
        if self._filtered:
            for i in range(self.tree.count()):
                if self.tree.item(i).data(Qt.ItemDataRole.UserRole):
                    self.tree.setCurrentRow(i)
                    break

    def _show(self, _row: int) -> None:
        item = self.tree.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        lines = [f"<h3>v{data.get('version')} {data.get('date')}</h3>", f"<p><b>{data.get('title')}</b></p>", "<ul>"]
        lines.extend(f"<li>{entry}</li>" for entry in data.get("items") or [])
        lines.append("</ul>")
        self.body.setHtml("".join(lines))


class JournalDialog(QDialog):
    def __init__(self, items: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Журнал изменений пользователей")
        configure_independent_window(self)
        self.resize(960, 560)
        self._items = items
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.kind = QComboBox()
        for value, label in (
            ("", "Все"),
            ("confirmed", "Ячейки"),
            ("parameter", "Параметры"),
            ("imported", "Импорт"),
            ("version", "Версии"),
            ("report", "Сводки"),
        ):
            self.kind.addItem(label, value)
        self.field = QComboBox()
        for value, label in (
            ("any", "Любое поле"),
            ("actor", "Кто"),
            ("object", "Объект"),
            ("action", "Действие"),
            ("comment", "Комментарий"),
            ("summary", "Изменения"),
        ):
            self.field.addItem(label, value)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Фильтр…")
        self.kind.currentIndexChanged.connect(self._rebuild)
        self.field.currentIndexChanged.connect(self._rebuild)
        self.query.textChanged.connect(self._rebuild)
        toolbar.addWidget(QLabel("Показать"))
        toolbar.addWidget(self.kind)
        toolbar.addWidget(QLabel("Поле"))
        toolbar.addWidget(self.field)
        toolbar.addWidget(self.query, 1)
        layout.addLayout(toolbar)
        views = QHBoxLayout()
        self.view_table = QPushButton("Таблица")
        self.view_feed = QPushButton("Лента")
        self.view_table.setCheckable(True)
        self.view_feed.setCheckable(True)
        self.view_table.setChecked(True)
        self.view_table.clicked.connect(lambda: self._set_view("table"))
        self.view_feed.clicked.connect(lambda: self._set_view("feed"))
        views.addWidget(self.view_table)
        views.addWidget(self.view_feed)
        views.addStretch(1)
        layout.addLayout(views)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Когда", "Кто", "Объект", "Действие", "Изменения", "Комментарий"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.feed = QTextBrowser()
        self.feed.hide()
        layout.addWidget(self.table, 1)
        layout.addWidget(self.feed, 1)
        self._view = "table"
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._rebuild()

    def _rebuild(self) -> None:
        kind = self.kind.currentData() or ""
        field = self.field.currentData() or "any"
        needle = self.query.text().strip().casefold()
        rows = []
        for item in self._items:
            action = item.get("action") or ""
            if kind == "parameter" and not action.startswith("parameter"):
                continue
            if kind and kind != "parameter" and action != kind:
                continue
            blob_map = {
                "any": f"{item.get('actor')} {item.get('object_name')} {item.get('action_label')} {item.get('summary')} {item.get('comment')}",
                "actor": item.get("actor") or "",
                "object": item.get("object_name") or "",
                "action": item.get("action_label") or "",
                "comment": item.get("comment") or "",
                "summary": item.get("summary") or "",
            }
            if needle and needle not in str(blob_map.get(field) or blob_map["any"]).casefold():
                continue
            rows.append(item)
        self.table.setRowCount(len(rows))
        for i, item in enumerate(rows):
            values = [
                item.get("created_at") or "",
                item.get("actor") or "",
                item.get("object_name") or "",
                item.get("action_label") or "",
                item.get("summary") or "",
                item.get("comment") or "",
            ]
            for col, value in enumerate(values):
                self.table.setItem(i, col, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        cards = []
        for item in rows:
            old = item.get("old_value") or ""
            new = item.get("new_value") or ""
            diff = ""
            if old or new:
                if old:
                    diff += f'<div style="color:#8b1a1a;background:#fdeaea;padding:2px 4px;">− {old}</div>'
                if new:
                    diff += f'<div style="color:#1b5e20;background:#e8f5e9;padding:2px 4px;">+ {new}</div>'
            else:
                diff = item.get("summary") or ""
            comment = f'<div style="color:#666">{item.get("comment") or ""}</div>' if item.get("comment") else ""
            cards.append(
                f'<div style="border:1px solid #d9e3f0;border-radius:8px;padding:8px 10px;margin-bottom:8px;background:#fff">'
                f'<b>{item.get("action_label") or ""}'
                f'{" · " + (item.get("object_name") or "") if item.get("object_name") else ""}</b>'
                f'<div style="color:#666">{item.get("actor") or ""} · {item.get("created_at") or ""}</div>'
                f'{diff}{comment}</div>'
            )
        self.feed.setHtml("".join(cards) or '<p style="color:#666">Записей нет</p>')

    def _set_view(self, view: str) -> None:
        self._view = view
        self.view_table.setChecked(view == "table")
        self.view_feed.setChecked(view == "feed")
        self.table.setVisible(view == "table")
        self.feed.setVisible(view == "feed")


class InstructionDialog(QDialog):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Инструкция")
        configure_independent_window(self)
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        view = QTextBrowser()
        view.setPlainText(text)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class UnsavedDialog(QDialog):
    def __init__(
        self,
        items: list[dict],
        parent: QWidget | None = None,
        allow_skip: bool = False,
        allow_discard: bool = True,
        skip_text: str = "Всё равно перейти",
        on_save=None,
        on_discard=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Несохранённые ячейки")
        self.resize(720, 460)
        self.skipped = False
        self._items = items
        self._comments: dict[int, QLineEdit] = {}
        self._actions: dict[int, str] = {}
        self._blocks: dict[int, QFrame] = {}
        self._on_save = on_save
        self._on_discard = on_discard
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Есть несохранённые черновики. Сохраните значение с комментарием. Отмена оставляет черновики в таблице."
            if not allow_discard
            else "Жёлтых ячеек быть не должно. Сохраните с комментарием или сбросьте черновик:"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QVBoxLayout(inner)
        for index, item in enumerate(items):
            block = QFrame()
            block.setStyleSheet("QFrame { border-bottom: 1px solid #eee; }")
            row = QVBoxLayout(block)
            row.addWidget(QLabel(f"{item.get('parameter_label') or ''} / {item.get('column_label') or ''}: {item.get('draft_value') or ''}"))
            actions = QHBoxLayout()
            comment = QLineEdit()
            comment.setPlaceholderText("Комментарий")
            self._comments[index] = comment
            save = QPushButton("Сохранить")
            save.clicked.connect(lambda _=False, i=index: self._save_row(i))
            actions.addWidget(comment, 1)
            actions.addWidget(save)
            if allow_discard:
                discard = QPushButton("Сбросить черновик")
                discard.clicked.connect(lambda _=False, i=index: self._discard_row(i))
                actions.addWidget(discard)
            row.addLayout(actions)
            form.addWidget(block)
            self._blocks[index] = block
        form.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        if allow_skip:
            skip = QPushButton(skip_text)
            skip.clicked.connect(self._skip)
            buttons.addWidget(skip)
        buttons.addStretch(1)
        close = QPushButton("Отмена" if not allow_discard else "Закрыть")
        close.clicked.connect(self.reject if not allow_discard else self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _remaining(self) -> int:
        return sum(1 for block in self._blocks.values() if block.isVisible())

    def _hide_row(self, index: int) -> None:
        block = self._blocks.get(index)
        if block:
            block.hide()
        if self._remaining() == 0:
            self.accept()

    def _save_row(self, index: int) -> None:
        comment = self._comments[index].text().strip()
        if not comment:
            self._comments[index].setFocus()
            return
        try:
            if self._on_save:
                self._on_save(self._items[index], comment)
        except Exception:
            return
        self._actions[index] = "confirm"
        self._hide_row(index)

    def _discard_row(self, index: int) -> None:
        try:
            if self._on_discard:
                self._on_discard(self._items[index])
        except Exception:
            return
        self._actions[index] = "discard"
        self._hide_row(index)

    def _skip(self) -> None:
        self.skipped = True
        self.accept()

    def results(self) -> list[tuple[dict, str, str]]:
        out = []
        for index, item in enumerate(self._items):
            action = self._actions.get(index)
            comment = self._comments[index].text().strip()
            if action:
                out.append((item, action, comment))
            elif comment:
                out.append((item, "confirm", comment))
        return out

    def comments(self) -> list[tuple[dict, str]]:
        return [(item, comment) for item, action, comment in self.results() if action == "confirm"]


class NotificationsDialog(QDialog):
    settings_requested = pyqtSignal()

    def __init__(self, items: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Уведомления")
        configure_independent_window(self)
        self.resize(560, 400)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        settings_btn = QPushButton("Настроить уведомления")
        settings_btn.clicked.connect(self.settings_requested.emit)
        toolbar.addWidget(settings_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.list = QListWidget()
        if items:
            for item in items:
                row = QListWidgetItem(item.get("text") or item.get("message") or str(item))
                row.setData(Qt.ItemDataRole.UserRole, item.get("id"))
                self.list.addItem(row)
        else:
            empty = QListWidgetItem("Нет уведомлений")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.selected_ids: list[str] = []
        self.list.itemDoubleClicked.connect(self._mark)

    def _mark(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id:
            self.selected_ids.append(str(note_id))
            item.setText(item.text() + " (прочитано)")


class NotificationSettingsDialog(QDialog):
    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройка уведомлений")
        configure_independent_window(self)
        self.resize(820, 480)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "По умолчанию приходят уведомления, если кто-то изменил ячейку, которую вы меняли раньше. "
            "Можно отключить это правило целиком или настроить каждый объект со сводкой отдельно: "
            "выключить объект, оставить только свои ячейки или получать все изменения ячеек."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.watch_mine = QCheckBox("Уведомлять об изменениях ячеек, которые я менял ранее")
        self.watch_mine.setChecked(bool(settings.get("watch_my_cells", True)))
        layout.addWidget(self.watch_mine)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Объект", "Уведомления", "Мои ячейки", "Все изменения"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self._object_rows: list[dict] = []
        for item in settings.get("objects") or []:
            self._add_object_row(item)
        if not self._object_rows:
            empty = QLabel("Нет объектов в работе. Настройки по объектам появятся, когда у объекта будет сводка.")
            empty.setProperty("role", "hint")
            empty.setWordWrap(True)
            layout.addWidget(empty)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.watch_mine.toggled.connect(self._sync_object_defaults)

    def _add_object_row(self, item: dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(item.get("object_name") or "")
        name.setData(Qt.ItemDataRole.UserRole, item.get("object_id"))
        self.table.setItem(row, 0, name)
        enabled = QCheckBox()
        enabled.setChecked(bool(item.get("enabled", True)))
        mine = QCheckBox()
        mine.setChecked(bool(item.get("watch_my_cells", True)))
        all_cells = QCheckBox()
        all_cells.setChecked(bool(item.get("watch_all_cells", False)))
        self.table.setCellWidget(row, 1, enabled)
        self.table.setCellWidget(row, 2, mine)
        self.table.setCellWidget(row, 3, all_cells)
        enabled.toggled.connect(lambda checked, mine_box=mine, all_box=all_cells: self._toggle_row(checked, mine_box, all_box))
        self._toggle_row(enabled.isChecked(), mine, all_cells)
        self._object_rows.append({"enabled": enabled, "watch_my_cells": mine, "watch_all_cells": all_cells})

    def _toggle_row(self, enabled: bool, mine: QCheckBox, all_cells: QCheckBox) -> None:
        mine.setEnabled(enabled)
        all_cells.setEnabled(enabled)

    def _sync_object_defaults(self, checked: bool) -> None:
        for row in self._object_rows:
            if row["enabled"].isChecked() and not row["watch_all_cells"].isChecked():
                row["watch_my_cells"].setChecked(checked)

    def payload(self) -> dict:
        objects = []
        for index, row in enumerate(self._object_rows):
            name_item = self.table.item(index, 0)
            objects.append(
                {
                    "object_id": name_item.data(Qt.ItemDataRole.UserRole) if name_item else "",
                    "object_name": name_item.text() if name_item else "",
                    "enabled": row["enabled"].isChecked(),
                    "watch_my_cells": row["watch_my_cells"].isChecked(),
                    "watch_all_cells": row["watch_all_cells"].isChecked(),
                }
            )
        return {"watch_my_cells": self.watch_mine.isChecked(), "objects": objects}


class IssuedKindDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, title: str = "Тип выдачи", prompt: str = "") -> None:
        super().__init__(parent)
        from desktop.ui.icons import issued_kind_icon
        from src.issued_kinds import CHOICES, DEFAULT

        self.setWindowTitle(title)
        self.resize(420, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        if prompt:
            label = QLabel(prompt)
            label.setWordWrap(True)
            layout.addWidget(label)
        kind_label = QLabel("Тип выдачи")
        kind_label.setProperty("role", "hint")
        layout.addWidget(kind_label)
        self.combo = QComboBox()
        for key, name in CHOICES:
            self.combo.addItem(issued_kind_icon(key), name, key)
        self.combo.setCurrentIndex(self.combo.findData(DEFAULT))
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_kind(self) -> str:
        return str(self.combo.currentData() or "")


def choose_issued_kind(parent: QWidget | None, title: str, prompt: str = "") -> str | None:
    dialog = IssuedKindDialog(parent, title=title, prompt=prompt)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_kind()
