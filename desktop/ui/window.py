from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.client import ApiClient, ApiError
from desktop.history import clear_keys, expected_at, take_snap, workbook_with_cell
from desktop.ui.chrome import MenuBar, TabStrip, Workspace
from desktop.ui.dialogs import (
    ChangelogDialog,
    GuideChoiceDialog,
    GuideOverlay,
    InstructionDialog,
    JournalDialog,
    NotificationsDialog,
    UnsavedDialog,
)
from desktop.ui.object_page import ObjectPage
from desktop.ui.report_page import ReportPage
from desktop.ui.table_page import TablePage
from desktop.ui.triangle_page import TrianglePage

APP_TOUR = [
    {"title": "Меню и справка", "body": "Файл обновляет окно. Стрелки влево/вправо — отменить и повторить действия этой сессии (Ctrl+Z / Ctrl+Y), как в Word. Справка — инструкция и журналы. Кнопка «?» снова открывает обучение.", "target": "guide-menu"},
    {"title": "Три вкладки", "body": "Сначала объект и треугольники, затем таблица исходных данных, затем отчёт. Без выбранного объекта таблица и отчёт закрыты.", "target": "guide-tabs", "tab": "object"},
    {"title": "Объект", "body": "Выберите турбину из списка. Если объекта нет — создайте его ниже или загрузите Excel.", "target": "guide-object", "tab": "object"},
    {"title": "Треугольники", "body": "Файл тепловиков заполняет ячейки по подписи параметра и номеру ступени. Импорт создаёт версию 0.", "target": "guide-triangle", "tab": "object"},
    {"title": "Таблица ИД", "body": "Параметры в строках, ступени и КУ в колонках. Жёлтый — черновик, зелёный — сохранено с комментарием.", "target": "guide-tab-table", "tab": "table"},
    {"title": "Отчёт", "body": "Короткая служебка или полная сводка в Word. Комментарии в файл не попадают.", "target": "guide-tab-report", "tab": "report"},
    {"title": "Уведомления", "body": "Если значение подтвердил другой автор, предыдущему приходит уведомление. Имя пользователя Windows подставляется само.", "target": "guide-notes"},
]

TABLE_TOUR = [
    {"title": "Режимы таблицы", "body": "По умолчанию — просмотр: клик по ячейке только выделяет строку и столбец и показывает историю. Чтобы вводить значения, включите режим редактирования.", "target": "guide-table-mode", "tab": "table"},
    {"title": "Цвета ячеек", "body": "Жёлтый — несохранённый черновик. Зелёный — зафиксировано. Серый — заголовок группы или поле, заблокированное правилом.", "target": "guide-colors", "tab": "table"},
    {"title": "Таблица", "body": "В режиме редактирования значение вводится в самой ячейке. Стрелки на клавиатуре переключают ячейки. Правка без комментария остаётся жёлтой.", "target": "guide-sheet", "tab": "table"},
    {"title": "Сохранение", "body": "Комментарий обязателен. Можно указать ссылку на чертёж — она уйдёт в Word, комментарий нет. «Отменить черновик» возвращает последнее сохранённое значение.", "target": "guide-edit", "tab": "table"},
    {"title": "Структура таблицы", "body": "«Редактировать структуру»: имя, единицы, уровень вложенности, добавление и удаление строк. Меняется только текущая сводка.", "target": "guide-add-param", "tab": "table"},
]


class MainWindow(QMainWindow):
    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client
        self.setWindowTitle("Гранд сводка ИД")
        self.resize(1280, 800)
        self.setMinimumSize(QSize(960, 640))

        self.username = ""
        self.can_write = True
        self.objects: list[dict] = []
        self.selected_id = ""
        self.workbook: dict | None = None
        self.catalog: dict | None = None
        self.unsaved: list[dict] = []
        self.sheets: list[dict] = []
        self.triangles: list[dict] = []
        self.busy = False
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.notes: list[dict] = []
        self.tab = "object"
        self.pending_tab: str | None = None
        self.history_position = "right"
        self.history_panel_open = True
        self.history_sizes = {"right": 360, "bottom": 260}
        self.guide_overlay: GuideOverlay | None = None

        self.object_page = ObjectPage()
        self.triangle_page = TrianglePage()
        self.table_page = TablePage()
        self.report_page = ReportPage()
        self.pages = {
            "object": self.object_page,
            "table": self.table_page,
            "triangles": self.triangle_page,
            "report": self.report_page,
        }

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.chrome = MenuBar()
        self.chrome.refresh_requested.connect(self._refresh_application)
        self.chrome.toggle_history_requested.connect(self._toggle_history_panel)
        self.chrome.history_position_requested.connect(self._set_history_position)
        self.chrome.instruction_requested.connect(self._show_instruction)
        self.chrome.about_requested.connect(self._about)
        self.chrome.changelog_requested.connect(self._show_changelog)
        self.chrome.journal_requested.connect(self._show_journal)
        self.chrome.guide_requested.connect(self._offer_guide)
        self.chrome.notes_requested.connect(self._show_notes)
        self.chrome.undo_requested.connect(self.undo_action)
        self.chrome.redo_requested.connect(self.redo_action)
        shell_layout.addWidget(self.chrome)

        workspace_wrap = QWidget()
        wrap = QVBoxLayout(workspace_wrap)
        wrap.setContentsMargins(14, 10, 14, 14)
        wrap.setSpacing(8)
        self.message_label = QLabel()
        self.message_label.setProperty("role", "ok")
        self.message_label.hide()
        self.error_label = QLabel()
        self.error_label.setProperty("role", "warn")
        self.error_label.hide()
        wrap.addWidget(self.error_label)
        wrap.addWidget(self.message_label)
        self.tab_strip = TabStrip()
        self.tab_strip.tab_changed.connect(self._try_change_tab)
        wrap.addWidget(self.tab_strip)
        self.workspace = Workspace()
        self.stack = QStackedWidget()
        for key in ("object", "table", "triangles", "report"):
            self.stack.addWidget(self.pages[key])
        self.workspace.layout_box.addWidget(self.stack)
        wrap.addWidget(self.workspace, 1)
        shell_layout.addWidget(workspace_wrap, 1)
        self.setCentralWidget(shell)
        self.menuBar().hide()

        self._connect_pages()
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo_action)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo_action)

        self.poll_notes = QTimer(self)
        self.poll_notes.timeout.connect(self._poll_notes)
        self.poll_notes.start(30_000)
        self.poll_revision = QTimer(self)
        self.poll_revision.timeout.connect(self._poll_revision)
        self.poll_revision.start(10_000)

        self.reload_all()
        self._load_history_prefs()
        self._maybe_guide()

    def _connect_pages(self) -> None:
        self.object_page.object_selected.connect(self.select_object)
        self.object_page.object_create_requested.connect(self.create_object)
        self.object_page.import_parameters_requested.connect(self._import_workbook)
        self.object_page.import_triangle_requested.connect(self._import_triangle)
        self.triangle_page.catalog_needed.connect(self._triangle_catalog)
        self.triangle_page.sync_requested.connect(self._sync_triangles)
        self.table_page.save_project_requested.connect(self._save_project)
        self.table_page.import_workbook_requested.connect(self._import_workbook)
        self.table_page.export_current_requested.connect(lambda: self._export_excel("current"))
        self.table_page.export_all_requested.connect(lambda: self._export_excel("all"))
        self.table_page.compose_report_requested.connect(self._compose_report)
        self.table_page.sheet_selected.connect(self.select_sheet)
        self.table_page.sheet_copy_requested.connect(self.copy_sheet)
        self.table_page.sheet_rename_requested.connect(self.rename_sheet)
        self.table_page.sheet_primary_requested.connect(self.set_primary_sheet)
        self.table_page.sheet_ordinary_requested.connect(self.unset_primary_sheet)
        self.table_page.sheet_delete_requested.connect(self.delete_sheet)
        self.table_page.draft_requested.connect(self._draft)
        self.table_page.confirm_requested.connect(self._confirm)
        self.table_page.discard_requested.connect(self._discard)
        self.table_page.unify_requested.connect(self._unify)
        self.table_page.history_needed.connect(self._load_history)
        self.table_page.add_parameter_requested.connect(self._add_parameter)
        self.table_page.update_parameter_requested.connect(self._update_parameter)
        self.table_page.delete_parameter_requested.connect(self._delete_parameter)
        self.table_page.add_column_requested.connect(self._add_column)
        self.table_page.update_column_requested.connect(self._update_column)
        self.table_page.delete_column_requested.connect(self._delete_column)
        self.table_page.comment_requested.connect(self._add_comment)
        self.table_page.last_comment_needed.connect(self._last_comment)
        self.table_page.save_all_drafts_requested.connect(self._open_unsaved)
        self.table_page.history_panel_toggled.connect(self._on_table_history_toggle)
        self.report_page.preview_requested.connect(self._load_report_sheet)
        self.report_page.export_requested.connect(self._export_report)

    def _set_busy(self, busy: bool) -> None:
        was = self.busy
        self.busy = busy
        if busy and not was:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        elif not busy and was:
            QApplication.restoreOverrideCursor()
        self._refresh_pages()

    def _info(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))
        self.error_label.hide()
        self.error_label.clear()

    def _fail(self, exc: Exception) -> None:
        message = str(exc)
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        if isinstance(exc, ApiError) and exc.status == 409:
            QMessageBox.warning(self, "Конфликт", "Ячейка уже изменена другим пользователем. Данные обновлены.")

    def _handle(self, exc: Exception) -> None:
        self._fail(exc)
        if self.workbook:
            try:
                self._reload_current()
            except Exception:
                pass

    def reload_all(self) -> None:
        try:
            me = self.client.me()
            self.username = me.get("username") or ""
            self.can_write = bool(me.get("can_write", True))
            self.chrome.set_user(self.username, self.can_write)
            self.objects = self.client.objects()
            self.notes = self.client.notifications()
            self.chrome.set_notes_count(sum(1 for item in self.notes if not item.get("read")))
            self._refresh_pages()
        except Exception as exc:
            self._fail(exc)

    def _refresh_pages(self) -> None:
        has_book = self.workbook is not None
        self.tab_strip.set_enabled(has_book, bool(self.triangles))
        self.tab_strip.set_current(self.tab)
        index = {"object": 0, "table": 1, "triangles": 2, "report": 3}[self.tab]
        self.stack.setCurrentIndex(index)
        self.object_page.set_objects(self.objects, self.selected_id)
        self.object_page.set_busy(self.busy, self.can_write, has_book)
        self.triangle_page.set_data(self.triangles, self.sheets, self.can_write, self.busy)
        object_name = next((item.get("name") or "" for item in self.objects if item.get("id") == self.selected_id), "")
        self.table_page.set_history_layout(self.history_position, self.history_panel_open, self.history_sizes)
        self.table_page.set_data(
            object_name=object_name,
            catalog=self.catalog,
            workbook=self.workbook,
            unsaved=self.unsaved,
            sheets=self.sheets,
            can_write=self.can_write,
            busy=self.busy,
        )
        self.report_page.set_sheets(self.sheets, (self.workbook or {}).get("id"))
        if self.workbook and self.catalog:
            self.report_page.set_table_data(self.catalog, self.workbook.get("cells") or [], self.busy)
        self._refresh_history_actions()
        self.chrome.set_history_prefs(self.history_panel_open, self.history_position)

    def _refresh_history_actions(self) -> None:
        can_undo = self.can_write and not self.busy and bool(self.undo_stack)
        can_redo = self.can_write and not self.busy and bool(self.redo_stack)
        undo_tip = f"Отменить: {self.undo_stack[-1]['label']} (Ctrl+Z)" if self.undo_stack else "Отменить (Ctrl+Z)"
        redo_tip = f"Повторить: {self.redo_stack[-1]['label']} (Ctrl+Y)" if self.redo_stack else "Повторить (Ctrl+Y)"
        self.chrome.set_history_actions(can_undo, can_redo, undo_tip, redo_tip)

    def _root_id(self) -> str | None:
        if not self.workbook:
            return None
        return self.workbook.get("parent_workbook_id") or self.workbook.get("id")

    def select_object(self, object_id: str) -> None:
        self.selected_id = object_id
        self._set_busy(True)
        try:
            opened = self.client.open_workbook(object_id)
            self._load_sheet_tree(opened.get("id"), opened.get("id"))
            self._info("Сводка открыта")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def create_object(self, payload: dict) -> None:
        self._set_busy(True)
        try:
            created = self.client.create_object(payload)
            self.objects = self.client.objects()
            self.selected_id = created["id"]
            opened = self.client.open_workbook(created["id"])
            self._load_sheet_tree(opened.get("id"), opened.get("id"))
            self._info("Объект добавлен в общий каталог")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def _load_sheet_tree(self, opened_id: str, active_id: str | None = None) -> None:
        sheets = self.client.sheets(opened_id)
        active = active_id or (sheets[0]["id"] if sheets else opened_id)
        self.workbook = self.client.workbook(active)
        self.catalog = self.client.catalog(active)
        self.unsaved = self.client.unsaved(active)
        self.sheets = sheets
        root = self._root_id() or opened_id
        self.triangles = self.client.triangles(root)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._refresh_pages()

    def _reload_current(self) -> None:
        if not self.workbook:
            return
        workbook_id = self.workbook["id"]
        self.workbook = self.client.workbook(workbook_id)
        self.catalog = self.client.catalog(workbook_id)
        self.unsaved = self.client.unsaved(workbook_id)
        root = self._root_id() or workbook_id
        self.sheets = self.client.sheets(root)
        self.triangles = self.client.triangles(root)
        self._refresh_pages()

    def select_sheet(self, sheet_id: str) -> None:
        if self.unsaved:
            self._fail(Exception("Сначала сохраните или отмените черновики текущего листа."))
            return
        self._set_busy(True)
        try:
            root = self._root_id()
            self._load_sheet_tree(root or sheet_id, sheet_id)
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def copy_sheet(self, sheet_id: str) -> None:
        source = next((item for item in self.sheets if item.get("id") == sheet_id), None)
        name, ok = QInputDialog.getText(self, "Копия листа", "Название нового листа", text=f"{(source or {}).get('name') or ''} — копия")
        if not ok or not name.strip():
            return
        self._set_busy(True)
        try:
            copy = self.client.copy_sheet(sheet_id, name.strip())
            self._load_sheet_tree(self._root_id() or copy["id"], copy["id"])
            self._info(f"Создан лист «{copy.get('sheet_name') or name}»")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def rename_sheet(self, sheet_id: str) -> None:
        source = next((item for item in self.sheets if item.get("id") == sheet_id), None)
        name, ok = QInputDialog.getText(self, "Переименовать лист", "Новое название листа", text=(source or {}).get("name") or "")
        if not ok or not name.strip():
            return
        self._set_busy(True)
        try:
            self.client.rename_sheet(self._root_id() or sheet_id, sheet_id, name.strip())
            self._reload_current()
            self._info(f"Лист переименован в «{name.strip()}».")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def set_primary_sheet(self, sheet_id: str) -> None:
        target = next((item for item in self.sheets if item.get("id") == sheet_id), None)
        current = next((item for item in self.sheets if item.get("is_primary")), None)
        if current and QMessageBox.question(
            self,
            "Основной лист",
            f"Основной лист сейчас «{current.get('name')}». Сделать «{(target or {}).get('name')}» основным?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        try:
            result = self.client.set_primary_sheet(self._root_id() or sheet_id, sheet_id)
            self.sheets = result.get("sheets") or self.sheets
            self._reload_current()
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def unset_primary_sheet(self, sheet_id: str) -> None:
        self._set_busy(True)
        try:
            result = self.client.unset_primary_sheet(self._root_id() or sheet_id, sheet_id)
            self.sheets = result.get("sheets") or self.sheets
            self._reload_current()
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def delete_sheet(self, sheet_id: str) -> None:
        target = next((item for item in self.sheets if item.get("id") == sheet_id), None)
        if QMessageBox.question(self, "Удалить лист", f"Удалить лист «{(target or {}).get('name')}»?") != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        try:
            result = self.client.delete_sheet(self._root_id() or sheet_id, sheet_id)
            self.sheets = result.get("sheets") or []
            active = result.get("active_sheet_id")
            if self.workbook and self.workbook.get("id") == sheet_id and active:
                self._load_sheet_tree(self._root_id() or active, active)
            else:
                self._reload_current()
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def _save_project(self) -> None:
        if not self.workbook:
            return
        if self.unsaved:
            dialog = UnsavedDialog(self.unsaved, self)
            if dialog.exec():
                for item, action, comment in dialog.results():
                    try:
                        if action == "confirm":
                            if not comment.strip():
                                self._fail(Exception("Укажите комментарий для каждой подтверждаемой ячейки."))
                                return
                            self.client.confirm_cell(
                                self.workbook["id"],
                                item["parameter_key"],
                                item["column_key"],
                                {
                                    "value": item.get("draft_value") or item.get("value") or "",
                                    "comment": comment,
                                    "expected_updated_at": expected_at(self.workbook, item["parameter_key"], item["column_key"]),
                                },
                            )
                        elif action == "discard":
                            self.client.discard_cell(self.workbook["id"], item["parameter_key"], item["column_key"])
                    except Exception as exc:
                        self._handle(exc)
                        return
        self._set_busy(True)
        try:
            result = self.client.save_project(self._root_id() or self.workbook["id"])
            self._reload_current()
            self._info(f"Проект сохранён ({result.get('cell_count') or 0} ячеек)")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def _import_workbook(self) -> None:
        if not self.workbook or not self.can_write:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Импортировать Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        self._set_busy(True)
        try:
            result = self.client.import_workbook(self.workbook["id"], Path(path))
            self.sheets = result.get("sheets") or self.sheets
            active = result.get("active_sheet_id") or self.workbook["id"]
            self._load_sheet_tree(self._root_id() or active, active)
            self._info(f"Импортировано значений: {result.get('imported') or 0}")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def _import_triangle(self) -> None:
        if not self.workbook:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Импортировать треугольники", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        self._set_busy(True)
        try:
            result = self.client.import_triangle(self._root_id() or self.workbook["id"], Path(path))
            self.triangles = result.get("sheets") or []
            self.tab = "triangles"
            self._refresh_pages()
            self._info("Импортированы листы «Геом. данные» и «Проточная часть».")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def _triangle_catalog(self, sheet_id: str) -> None:
        try:
            self.triangle_page.set_catalog(self.client.catalog(sheet_id))
        except Exception as exc:
            self._fail(exc)

    def _sync_triangles(self, target_id: str, mode: str, cells: list, param) -> None:
        if mode == "all" and QMessageBox.question(
            self,
            "Перенос треугольников",
            "Все сопоставимые параметры треугольников заменят соответствующие значения в выбранном листе ИД. Продолжить?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        try:
            pending = self.client.unsaved(target_id)
            if pending:
                self._fail(Exception("Сначала сохраните или отмените черновики на выбранном листе ИД."))
                return
            result = self.client.sync_triangles(
                target_id,
                {"mode": mode, "cells": cells, "target_parameter_key": param},
            )
            self._load_sheet_tree(self._root_id() or target_id, target_id)
            self.tab = "table"
            extra = result.get("unsupported_fields") or []
            unsupported = f" Не перенесены: {', '.join(extra)}." if extra else ""
            self._info(
                f"Треугольники синхронизированы: записано {result.get('updated')}, очищено {result.get('cleared')}, "
                f"пропущено {int(result.get('skipped') or 0) + int(result.get('conflicts') or 0)}.{unsupported}"
            )
        except Exception as exc:
            self._fail(exc)
        finally:
            self._set_busy(False)

    def _export_excel(self, scope: str) -> None:
        if not self.workbook:
            return
        suggested = "grand_summary.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить Excel", suggested, "Excel (*.xlsx)")
        if not path:
            return
        try:
            data = self.client.export_excel(self.workbook["id"], scope)
            Path(path).write_bytes(data)
            self._info("Файл сохранён")
        except Exception as exc:
            self._fail(exc)

    def _compose_report(self) -> None:
        if self.unsaved:
            self._fail(Exception("Сначала сохраните или отмените черновики текущего листа."))
            return
        self.tab = "report"
        self._refresh_pages()
        if self.workbook and self.catalog:
            self.report_page.set_table_data(self.catalog, self.workbook.get("cells") or [])

    def _load_report_sheet(self, sheet_id: str, _type: str) -> None:
        try:
            book = self.client.workbook(sheet_id)
            catalog = self.client.catalog(sheet_id)
            self.report_page.set_table_data(catalog, book.get("cells") or [])
        except Exception as exc:
            self._fail(exc)

    def _export_report(self, sheet_id: str, params: list, cols: list) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить Word", "таблица_ид.docx", "Word (*.docx)")
        if not path:
            return
        try:
            data = self.client.export_report_table(sheet_id, params, cols)
            Path(path).write_bytes(data)
            self._info("Отчёт сохранён")
        except Exception as exc:
            self._fail(exc)

    def _record(self, previous: dict, previous_catalog: dict | None, label: str, kind: str, keys: dict, next_book: dict, extra: dict | None = None) -> None:
        before = take_snap(previous, previous_catalog)
        after = take_snap(next_book, self.catalog, extra)
        entry = {"label": label, "kind": kind, "parameterKey": keys.get("parameterKey"), "columnKey": keys.get("columnKey"), "before": before, "after": after}
        if (
            self.undo_stack
            and kind == "draft"
            and self.undo_stack[-1]["kind"] == "draft"
            and self.undo_stack[-1].get("parameterKey") == entry["parameterKey"]
            and self.undo_stack[-1].get("columnKey") == entry["columnKey"]
        ):
            self.undo_stack[-1]["after"] = after
        else:
            self.undo_stack.append(entry)
        self.redo_stack.clear()
        self.workbook = next_book
        try:
            self.unsaved = self.client.unsaved(next_book["id"])
        except Exception:
            pass
        self._refresh_pages()

    def _draft(self, parameter_key: str, column_key: str, value: str, hyperlink) -> None:
        if not self.workbook:
            return
        previous = self.workbook
        previous_catalog = self.catalog
        try:
            cell = self.client.patch_cell(
                self.workbook["id"],
                parameter_key,
                column_key,
                {"value": value, "hyperlink": hyperlink, "expected_updated_at": expected_at(self.workbook, parameter_key, column_key)},
            )
            next_book = workbook_with_cell(previous, cell)
            self._record(previous, previous_catalog, "Ввод в ячейке", "draft", {"parameterKey": parameter_key, "columnKey": column_key}, next_book)
        except Exception as exc:
            self._handle(exc)

    def _confirm(self, parameter_key: str, column_key: str, value: str, comment: str, hyperlink) -> None:
        if not self.workbook:
            return
        if not comment.strip():
            self._fail(Exception("Комментарий обязателен для подтверждения ячейки."))
            return
        previous = self.workbook
        previous_catalog = self.catalog
        try:
            cell = self.client.confirm_cell(
                self.workbook["id"],
                parameter_key,
                column_key,
                {
                    "value": value,
                    "comment": comment,
                    "hyperlink": hyperlink,
                    "expected_updated_at": expected_at(self.workbook, parameter_key, column_key),
                },
            )
            next_book = workbook_with_cell(previous, cell)
            log = self.client.history(self.workbook["id"], parameter_key, column_key)
            self.table_page.set_history(log)
            last = log[0] if log else None
            extra = {
                "changeIds": [cell["last_change_id"]] if cell.get("last_change_id") else ([last["id"]] if last else []),
                "changes": [
                    {
                        "id": last["id"],
                        "parameter_key": parameter_key,
                        "column_key": column_key,
                        "author": last.get("author"),
                        "old_value": last.get("old_value"),
                        "new_value": last.get("new_value"),
                        "comment": last.get("comment"),
                    }
                ]
                if last
                else [],
            }
            self._record(previous, previous_catalog, "Сохранение значения", "confirm", {"parameterKey": parameter_key, "columnKey": column_key}, next_book, extra)
        except Exception as exc:
            self._handle(exc)

    def _discard(self, parameter_key: str, column_key: str) -> None:
        if not self.workbook:
            return
        previous = self.workbook
        previous_catalog = self.catalog
        try:
            cell = self.client.discard_cell(self.workbook["id"], parameter_key, column_key)
            next_book = workbook_with_cell(previous, cell)
            self._record(previous, previous_catalog, "Отмена черновика", "discard", {"parameterKey": parameter_key, "columnKey": column_key}, next_book)
        except Exception as exc:
            self._handle(exc)

    def _unify(self, parameter_key: str, column_key: str, unified: bool) -> None:
        if not self.workbook:
            return
        try:
            cell = self.client.set_cell_unification(self.workbook["id"], parameter_key, column_key, {"unified": unified})
            self.workbook = workbook_with_cell(self.workbook, cell)
            self._refresh_pages()
        except Exception as exc:
            self._handle(exc)

    def _load_history(self, parameter_key: str, column_key: str) -> None:
        if not self.workbook:
            return
        try:
            self.table_page.set_history(self.client.history(self.workbook["id"], parameter_key, column_key))
        except Exception as exc:
            self._fail(exc)

    def _after_structure(self, previous: dict, previous_catalog: dict | None, label: str) -> None:
        if not self.workbook:
            return
        next_book = self.client.workbook(self.workbook["id"])
        self.catalog = self.client.catalog(self.workbook["id"])
        self._record(previous, previous_catalog, label, "structure", {}, next_book)

    def _add_parameter(self, body: dict) -> None:
        if not self.workbook:
            return
        previous, previous_catalog = self.workbook, self.catalog
        try:
            self.client.add_parameter(self.workbook["id"], body)
            self._after_structure(previous, previous_catalog, "Добавление параметра")
        except Exception as exc:
            self._handle(exc)

    def _update_parameter(self, key: str, body: dict) -> None:
        if not self.workbook:
            return
        previous, previous_catalog = self.workbook, self.catalog
        try:
            self.client.update_parameter(self.workbook["id"], key, body)
            self._after_structure(previous, previous_catalog, "Изменение параметра")
        except Exception as exc:
            self._handle(exc)

    def _delete_parameter(self, key: str) -> None:
        if not self.workbook:
            return
        if QMessageBox.question(self, "Удалить строку", "Удалить выбранную строку из этой сводки?") != QMessageBox.StandardButton.Yes:
            return
        previous, previous_catalog = self.workbook, self.catalog
        try:
            self.client.delete_parameter(self.workbook["id"], key)
            self._after_structure(previous, previous_catalog, "Удаление параметра")
        except Exception as exc:
            self._handle(exc)

    def _add_column(self, label: str) -> None:
        if not self.workbook:
            return
        previous, previous_catalog = self.workbook, self.catalog
        try:
            self.client.add_stage(self.workbook["id"], label)
            self._after_structure(previous, previous_catalog, "Добавление столбца")
        except Exception as exc:
            self._handle(exc)

    def _update_column(self, key: str, label: str) -> None:
        if not self.workbook:
            return
        previous, previous_catalog = self.workbook, self.catalog
        try:
            self.client.update_column(self.workbook["id"], key, label)
            self._after_structure(previous, previous_catalog, "Переименование столбца")
        except Exception as exc:
            self._handle(exc)

    def _delete_column(self, key: str) -> None:
        if not self.workbook:
            return
        if QMessageBox.question(self, "Удалить столбец", "Удалить столбец с этого листа?") != QMessageBox.StandardButton.Yes:
            return
        previous, previous_catalog = self.workbook, self.catalog
        try:
            self.client.delete_column(self.workbook["id"], key)
            self._after_structure(previous, previous_catalog, "Удаление столбца")
        except Exception as exc:
            self._handle(exc)

    def _in_plain_field(self) -> bool:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit)):
            parent = focus.parent()
            while parent is not None:
                if isinstance(parent, QTableWidget):
                    return False
                parent = parent.parent()
            return True
        return False

    def undo_action(self) -> None:
        if self._in_plain_field():
            return
        if not self.can_write or self.busy or not self.undo_stack or not self.workbook:
            return
        entry = self.undo_stack.pop()
        self.redo_stack.append(entry)
        self._apply_history(entry, "undo")

    def redo_action(self) -> None:
        if self._in_plain_field():
            return
        if not self.can_write or self.busy or not self.redo_stack or not self.workbook:
            return
        entry = self.redo_stack.pop()
        self.undo_stack.append(entry)
        self._apply_history(entry, "redo")

    def _apply_history(self, entry: dict, direction: str) -> None:
        if not self.workbook:
            return
        target = entry["before"] if direction == "undo" else entry["after"]
        other = entry["after"] if direction == "undo" else entry["before"]
        try:
            next_book = self.client.restore_session(
                self.workbook["id"],
                {
                    "cells": target["cells"],
                    "extra_columns": target["extra_columns"],
                    "column_overrides": target["column_overrides"],
                    "deleted_columns": target["deleted_columns"],
                    "extra_parameters": target["extra_parameters"],
                    "parameter_overrides": target["parameter_overrides"],
                    "deleted_parameters": target["deleted_parameters"],
                    "remove_change_ids": entry["after"]["changeIds"] if direction == "undo" else [],
                    "add_changes": entry["after"]["changes"] if direction == "redo" else [],
                    "clear_keys": [
                        {"parameter_key": item["parameter_key"], "column_key": item["column_key"]}
                        for item in clear_keys(other["cells"], target["cells"])
                    ],
                },
            )
            self.workbook = next_book
            self.catalog = self.client.catalog(next_book["id"])
            self.unsaved = self.client.unsaved(next_book["id"])
            self._refresh_pages()
        except Exception as exc:
            self._handle(exc)

    def _try_change_tab(self, next_tab: str) -> None:
        if next_tab != "object" and self.unsaved:
            self.pending_tab = next_tab
            self._open_unsaved()
            self.tab_strip.set_current(self.tab)
            return
        self.tab = next_tab
        self._refresh_pages()

    def _open_unsaved(self) -> None:
        if not self.unsaved or not self.workbook:
            return
        dialog = UnsavedDialog(self.unsaved, self, allow_skip=bool(self.pending_tab))
        result = dialog.exec()
        if dialog.skipped and self.pending_tab:
            self.tab = self.pending_tab
            self.pending_tab = None
            self._refresh_pages()
            return
        if not result:
            self.pending_tab = None
            return
        for item, action, comment in dialog.results():
            try:
                if action == "confirm":
                    self.client.confirm_cell(
                        self.workbook["id"],
                        item["parameter_key"],
                        item["column_key"],
                        {
                            "value": item.get("draft_value") or item.get("value") or "",
                            "comment": comment,
                            "expected_updated_at": expected_at(self.workbook, item["parameter_key"], item["column_key"]),
                        },
                    )
                elif action == "discard":
                    self.client.discard_cell(self.workbook["id"], item["parameter_key"], item["column_key"])
            except Exception as exc:
                self._handle(exc)
                return
        self._reload_current()
        if not self.unsaved and self.pending_tab:
            self.tab = self.pending_tab
            self.pending_tab = None
            self._refresh_pages()

    def _refresh_application(self) -> None:
        try:
            status = self.client.update_status()
        except Exception as exc:
            self._fail(exc)
            return
        if not status.get("supported"):
            self.reload_all()
            self._info("Окно обновлено.")
            return
        if not status.get("enabled"):
            self._info(status.get("message") or "Источник обновлений не настроен.")
            return
        if not status.get("update_available"):
            self._info(f"Установлена последняя версия ({status.get('current_version')}).")
            return
        latest = status.get("latest_version") or "новая версия"
        if QMessageBox.question(self, "Обновление", f"Доступна версия {latest}. Обновить и перезапустить приложение?") != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.client.apply_update()
            self._info(f"Обновление до версии {result.get('version')} запущено. Приложение перезапустится.")
        except Exception as exc:
            self._fail(exc)

    def _toggle_history_panel(self) -> None:
        self.history_panel_open = not self.history_panel_open
        self._save_history_prefs()
        self._refresh_pages()

    def _set_history_position(self, position: str) -> None:
        self.history_position = position
        self.history_panel_open = True
        self._save_history_prefs()
        self._refresh_pages()

    def _on_table_history_toggle(self, opened: bool) -> None:
        self.history_panel_open = opened
        self._save_history_prefs()
        self.chrome.set_history_prefs(self.history_panel_open, self.history_position)

    def _load_history_prefs(self) -> None:
        try:
            prefs = self.client.history_preferences()
        except Exception:
            return
        if not prefs.get("configured"):
            return
        self.history_position = prefs.get("history_position") or "right"
        self.history_panel_open = bool(prefs.get("history_panel_open", True))
        self.history_sizes = {
            "right": int(prefs.get("history_right_width") or 360),
            "bottom": int(prefs.get("history_bottom_height") or 260),
        }
        self.table_page.set_history_layout(self.history_position, self.history_panel_open, self.history_sizes)
        self.chrome.set_history_prefs(self.history_panel_open, self.history_position)

    def _save_history_prefs(self) -> None:
        try:
            self.client.save_history_preferences(
                {
                    "history_position": self.history_position,
                    "history_panel_open": self.history_panel_open,
                    "history_right_width": self.history_sizes["right"],
                    "history_bottom_height": self.history_sizes["bottom"],
                }
            )
        except Exception:
            pass

    def _poll_notes(self) -> None:
        try:
            self.notes = self.client.notifications()
            self.chrome.set_notes_count(sum(1 for item in self.notes if not item.get("read")))
        except Exception:
            pass

    def _poll_revision(self) -> None:
        if not self.workbook or self.busy:
            return
        try:
            current = self.client.workbook(self.workbook["id"])
            if current.get("updated_at") != self.workbook.get("updated_at"):
                self._reload_current()
        except Exception:
            pass

    def _add_comment(self, parameter_key: str, column_key: str, comment: str) -> None:
        if not self.workbook:
            return
        try:
            cell = self.client.add_cell_comment(
                self.workbook["id"],
                parameter_key,
                column_key,
                {"comment": comment, "expected_updated_at": expected_at(self.workbook, parameter_key, column_key)},
            )
            self.workbook = workbook_with_cell(self.workbook, cell)
            self._load_history(parameter_key, column_key)
            self._refresh_pages()
        except Exception as exc:
            self._handle(exc)

    def _last_comment(self, parameter_key: str, column_key: str) -> None:
        if not self.workbook:
            return
        try:
            text = self.client.last_cell_comment(self.workbook["id"], parameter_key, column_key)
            self.table_page.show_comment_tooltip(text)
        except Exception:
            self.table_page.show_comment_tooltip(None)

    def _offer_guide(self) -> None:
        choice = GuideChoiceDialog(self)
        if not choice.exec():
            self._mark_guide_seen()
            return
        self._start_guide(choice.kind)

    def _start_guide(self, kind: str) -> None:
        steps = APP_TOUR if kind == "app" else TABLE_TOUR
        if kind == "table":
            self.tab = "table"
            self._refresh_pages()
        if self.guide_overlay:
            self.guide_overlay.close()
        self.guide_overlay = GuideOverlay(steps, self, self._guide_focus)
        self.guide_overlay.finished.connect(self._mark_guide_seen)
        self.guide_overlay.show()

    def _guide_focus(self, step: dict) -> None:
        tab = step.get("tab")
        if tab:
            self.tab = tab
            self._refresh_pages()

    def _mark_guide_seen(self) -> None:
        try:
            self.client.mark_guide_seen()
        except Exception:
            pass

    def _maybe_guide(self) -> None:
        try:
            me = self.client.me()
        except Exception:
            return
        if me.get("guide_seen"):
            return
        QTimer.singleShot(700, self._offer_guide)

    def _show_instruction(self) -> None:
        try:
            text = self.client.instruction().get("text") or ""
        except Exception as exc:
            self._fail(exc)
            return
        InstructionDialog(text, self).exec()

    def _show_changelog(self) -> None:
        try:
            data = self.client.changelog()
        except Exception as exc:
            self._fail(exc)
            return
        ChangelogDialog(data.get("releases") or [], self).exec()

    def _show_journal(self) -> None:
        try:
            items = self.client.journal(self.workbook["id"] if self.workbook else None)
        except Exception as exc:
            self._fail(exc)
            return
        JournalDialog(items, self).exec()

    def _show_notes(self) -> None:
        dialog = NotificationsDialog(self.notes, self)
        dialog.exec()
        for note_id in dialog.selected_ids:
            try:
                self.client.read_notification(note_id)
            except Exception:
                pass
        try:
            self.notes = self.client.notifications()
            self.chrome.set_notes_count(sum(1 for item in self.notes if not item.get("read")))
        except Exception:
            pass

    def _about(self) -> None:
        try:
            data = self.client.changelog()
            version = data.get("app_version") or ""
        except Exception:
            from src.app_info import APP_VERSION

            version = APP_VERSION
        rights = "ОР (запись)" if self.can_write else "просмотр"
        QMessageBox.information(
            self,
            "О приложении",
            f"Гранд сводка ИД {version}\nПользователь: {self.username}\nПрава: {rights}\nСистема управления исходными данными проточных частей турбин.",
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.guide_overlay:
            self.guide_overlay.setGeometry(self.rect())
            self.guide_overlay._place()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.unsaved:
            if QMessageBox.question(self, "Черновики", "Есть несохранённые черновики. Закрыть окно?") != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._save_history_prefs()
        try:
            self.client.close()
        except Exception:
            pass
        super().closeEvent(event)
