from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.attributes import set_committed_value

from backend.models import Cell, CellChange, Notification, ObjectItem, TriangleSheet, Version, Workbook
from src.catalog import column_by_key, columns, parameter_by_key, parameters
from src.issued_kinds import LABELS as ISSUED_KIND_LABELS
from src.issued_kinds import issued_kind_label, normalize_issued_kind
from src.services.decimals import normalize_decimal_commas
from src.services.journal import add_audit
from src.services.rules import all_lock_keys, matching_rules, options_for
from src.services.notification_settings import recipients_for_cell_change
from src.services.sheet_compare import combine_compare_targets, values_differ


PRIMARY_ORIGIN_COMMENT = "Данные из основного листа"
EXCEL_SHEET_COMMENT_PREFIX = "Изменение листа «"
MAIN_SHEET_NAME = "Основная таблица"
PLACEHOLDER_MAIN_NAMES = frozenset(
    {
        "исходные данные",
        "основной лист",
        "основная таблица",
    }
)


def excel_sheet_comment(name: str) -> str:
    return f"{EXCEL_SHEET_COMMENT_PREFIX}{name}»"


class CellConflict(Exception):
    def __init__(self, payload: dict):
        super().__init__("Ячейка уже изменена другим пользователем")
        self.payload = payload


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _display(cell: Cell) -> str | None:
    raw = cell.draft_value if cell.status == "draft" and cell.draft_value is not None else cell.value
    if raw is None:
        return None
    return normalize_decimal_commas(raw)


def extra_columns(workbook: Workbook) -> list[dict]:
    raw = workbook.extra_columns_json or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def extra_parameters(workbook: Workbook) -> list[dict]:
    raw = getattr(workbook, "extra_parameters_json", None) or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def parameter_overrides(workbook: Workbook) -> dict:
    raw = getattr(workbook, "parameter_overrides_json", None) or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def deleted_parameter_keys(workbook: Workbook) -> set[str]:
    raw = getattr(workbook, "deleted_parameters_json", None) or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return {str(item) for item in data} if isinstance(data, list) else set()


def _save_json(workbook: Workbook, field: str, payload) -> None:
    setattr(workbook, field, json.dumps(payload, ensure_ascii=False))


def _report_notes_raw(workbook: Workbook) -> list[dict]:
    raw = getattr(workbook, "report_notes_json", None) or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    notes = []
    for item in data:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        notes.append(
            {
                "id": str(item.get("id") or ""),
                "parameter_key": str(item.get("parameter_key") or ""),
                "column_key": str(item.get("column_key") or ""),
                "text": str(item.get("text") or "").strip(),
                "created_at": str(item.get("created_at") or ""),
                "author": str(item.get("author") or ""),
            }
        )
    notes.sort(key=lambda item: (item["created_at"], item["id"]))
    return notes


def report_notes(workbook: Workbook) -> list[dict]:
    notes = _report_notes_raw(workbook)
    numbered = []
    for index, item in enumerate(notes, start=1):
        row = dict(item)
        row["number"] = index
        numbered.append(row)
    return numbered


def add_report_note(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    text: str,
    username: str = "",
) -> list[dict]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Введите текст примечания")
    if not (parameter_key or "").strip() or not (column_key or "").strip():
        raise ValueError("Выберите ячейку для примечания")
    notes = _report_notes_raw(workbook)
    notes.append(
        {
            "id": _new_id(),
            "parameter_key": parameter_key.strip(),
            "column_key": column_key.strip(),
            "text": cleaned,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "author": username,
        }
    )
    _save_json(workbook, "report_notes_json", notes)
    workbook.updated_at = datetime.now(timezone.utc)
    session.flush()
    return report_notes(workbook)


def delete_report_note(session: Session, workbook: Workbook, note_id: str) -> list[dict]:
    notes = _report_notes_raw(workbook)
    remaining = [item for item in notes if item["id"] != note_id]
    if len(remaining) == len(notes):
        raise ValueError("Примечание не найдено")
    _save_json(workbook, "report_notes_json", remaining)
    workbook.updated_at = datetime.now(timezone.utc)
    session.flush()
    return report_notes(workbook)


def column_overrides(workbook: Workbook) -> dict:
    raw = getattr(workbook, "column_overrides_json", None) or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def deleted_column_keys(workbook: Workbook) -> set[str]:
    raw = getattr(workbook, "deleted_columns_json", None) or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return {str(item) for item in data} if isinstance(data, list) else set()


def workbook_columns(workbook: Workbook) -> list[dict]:
    overrides = column_overrides(workbook)
    deleted = deleted_column_keys(workbook)
    result = []
    for item in [*columns(), *extra_columns(workbook)]:
        key = item["key"]
        if key in deleted:
            continue
        column = dict(item)
        label = overrides.get(key)
        if isinstance(label, str) and label.strip():
            column["label"] = label
        result.append(column)
    return result


def workbook_parameters(workbook: Workbook | None = None) -> list[dict]:
    items = [dict(item) for item in parameters()]
    if workbook is None:
        return items
    deleted = deleted_parameter_keys(workbook)
    overrides = parameter_overrides(workbook)
    result: list[dict] = []
    for item in items:
        if item["key"] in deleted:
            continue
        extra = overrides.get(item["key"]) or {}
        if extra:
            item.update({key: value for key, value in extra.items() if value is not None})
        result.append(item)
    for extra in extra_parameters(workbook):
        if extra.get("key") in deleted:
            continue
        row = dict(extra)
        patch = overrides.get(row["key"]) or {}
        if patch:
            row.update({key: value for key, value in patch.items() if value is not None})
        result.append(row)
    result.sort(key=lambda item: (item.get("order", 0), item.get("key", "")))
    return result


def resolve_parameter(workbook: Workbook, key: str) -> dict | None:
    for item in workbook_parameters(workbook):
        if item["key"] == key:
            return item
    return parameter_by_key(key)


def resolve_column(workbook: Workbook, key: str) -> dict | None:
    for item in workbook_columns(workbook):
        if item["key"] == key:
            return item
    if key in deleted_column_keys(workbook):
        return None
    return column_by_key(key)


def editable_keys(workbook: Workbook) -> set[str]:
    return {item["key"] for item in workbook_parameters(workbook) if item.get("row_kind") == "editable"}


def cell_to_dict(cell: Cell, workbook: Workbook | None = None) -> dict:
    locked = bool(cell.locked)
    param_key = cell.parameter_key
    return {
        "parameter_key": param_key,
        "column_key": cell.column_key,
        "value": cell.value,
        "draft_value": cell.draft_value,
        "status": cell.status,
        "hyperlink": cell.hyperlink,
        "display": _display(cell),
        "locked": locked,
        "unified": bool(cell.unified),
        "excel_highlight": bool(cell.excel_highlight),
        "compare_highlight": False,
        "compare_against": [],
        "updated_at": _iso(cell.updated_at),
        "updated_by": cell.updated_by,
        "options": options_for(param_key),
        "last_change_id": getattr(cell, "last_change_id", None),
    }


def snapshot_cells(workbook: Workbook) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for cell in effective_cells(workbook):
        result.setdefault(cell.parameter_key, {})[cell.column_key] = cell.value
    return result


def hyperlinks_map(workbook: Workbook) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for cell in effective_cells(workbook):
        if cell.hyperlink:
            result.setdefault(cell.parameter_key, {})[cell.column_key] = cell.hyperlink
    return result


def get_workbook(session: Session, workbook_id: str) -> Workbook | None:
    return session.get(Workbook, workbook_id)


def list_sheet_workbooks(session: Session, workbook: Workbook) -> list[Workbook]:
    root = workbook.parent or workbook
    return (
        session.query(Workbook)
        .filter((Workbook.id == root.id) | (Workbook.parent_workbook_id == root.id))
        .order_by(Workbook.sheet_order, Workbook.created_at)
        .all()
    )


def delete_sheet_workbook(session: Session, root: Workbook, target: Workbook) -> tuple[list[Workbook], str]:
    sheets = list_sheet_workbooks(session, root)
    if target.id not in {item.id for item in sheets}:
        raise ValueError("Лист не найден в проекте")
    remaining = [item for item in sheets if item.id != target.id]
    if target.is_base:
        raise ValueError("Базовый лист нельзя удалить")
    if target.is_primary:
        raise ValueError("Основную таблицу нельзя удалить")
    if not remaining:
        raise ValueError("Нельзя удалить единственный лист проекта")
    successor = remaining[0]
    if target.id == root.id:
        for item in remaining:
            item.parent_workbook_id = None if item.id == successor.id else successor.id
        existing_keys = {
            key
            for (key,) in session.query(TriangleSheet.sheet_key).filter(TriangleSheet.workbook_id == successor.id)
        }
        movable = session.query(TriangleSheet).filter(TriangleSheet.workbook_id == target.id)
        if existing_keys:
            movable = movable.filter(~TriangleSheet.sheet_key.in_(existing_keys))
        movable.update({"workbook_id": successor.id}, synchronize_session=False)
        session.flush()
        session.expire(target, ["sheets", "triangle_sheets"])
        session.delete(target)
        new_root = successor
    else:
        session.delete(target)
        new_root = root
    session.flush()
    sheets = list_sheet_workbooks(session, new_root)
    for order, item in enumerate(sheets):
        item.sheet_order = order
    new_root.updated_at = _now()
    session.flush()
    active_id = successor.id if target.id == root.id else sheets[0].id
    return sheets, active_id


def set_primary_sheet(session: Session, workbook: Workbook, username: str) -> list[Workbook]:
    root = workbook.parent or workbook
    sheets = list_sheet_workbooks(session, root)
    if all(item.id != workbook.id for item in sheets):
        raise ValueError("Лист не найден в проекте")
    old_primary = next((item for item in sheets if item.is_primary), None)
    if old_primary and old_primary.id == workbook.id:
        return sheets
    if workbook.is_issued:
        raise ValueError("Снимите отметку «Версия выдана», прежде чем сделать лист основным")
    if any(item.is_base and item.id != workbook.id for item in sheets):
        raise ValueError("Основной лист задаёт базовый. Назначьте базовым другой лист, если нужно сменить начало проекта")

    for item in sheets:
        item.is_primary = item.id == workbook.id
    ordered = [workbook, *(item for item in sheets if item.id != workbook.id)]
    for order, item in enumerate(ordered):
        item.sheet_order = order
    root.updated_at = _now()
    old_name = old_primary.sheet_name if old_primary else "не назначен"
    add_audit(
        session,
        actor=username,
        action="primary_sheet_changed",
        workbook=root,
        old_value=old_primary.sheet_name if old_primary else None,
        new_value=workbook.sheet_name,
        summary=f"Основной лист изменён с «{old_name}» на «{workbook.sheet_name}»",
    )
    session.flush()
    return ordered


def unset_primary_sheet(session: Session, workbook: Workbook, username: str) -> list[Workbook]:
    root = workbook.parent or workbook
    sheets = list_sheet_workbooks(session, root)
    if all(item.id != workbook.id for item in sheets):
        raise ValueError("Лист не найден в проекте")
    if not workbook.is_primary:
        return sheets
    if workbook.is_base:
        raise ValueError("Базовый лист нельзя сделать обычным")

    workbook.is_primary = False
    root.updated_at = _now()
    add_audit(
        session,
        actor=username,
        action="primary_sheet_removed",
        workbook=root,
        old_value=workbook.sheet_name,
        new_value=None,
        summary=f"С листа «{workbook.sheet_name}» снят статус основного",
    )
    session.flush()
    return sheets


def rename_sheet(session: Session, workbook: Workbook, name: str, username: str) -> Workbook:
    root = workbook.parent or workbook
    cleaned_name = name.strip()
    if workbook.is_base:
        raise ValueError("Базовый лист нельзя переименовать")
    if not cleaned_name:
        raise ValueError("Укажите название листа")
    siblings = list_sheet_workbooks(session, root)
    if workbook not in siblings:
        raise ValueError("Лист не найден в проекте")
    if any(item.id != workbook.id and item.sheet_name.casefold() == cleaned_name.casefold() for item in siblings):
        raise ValueError("Лист с таким названием уже существует")
    old_name = workbook.sheet_name
    workbook.sheet_name = cleaned_name[:255]
    workbook.updated_at = _now()
    add_audit(
        session,
        actor=username,
        action="sheet_renamed",
        workbook=root,
        old_value=old_name,
        new_value=workbook.sheet_name,
        summary=f"Лист «{old_name}» переименован в «{workbook.sheet_name}»",
    )
    session.flush()
    return workbook


def ensure_workbook(session: Session, object_item: ObjectItem, username: str) -> tuple[Workbook, bool]:
    from src.services.objects import workbook_for_object

    existing = workbook_for_object(session, object_item.id)
    if existing:
        return existing, False
    workbook = Workbook(
        id=_new_id(),
        object_id=object_item.id,
        created_by=username,
        is_primary=True,
        sheet_name=MAIN_SHEET_NAME,
        extra_columns_json="[]",
        extra_parameters_json="[]",
        parameter_overrides_json="{}",
        deleted_parameters_json="[]",
        report_notes_json="[]",
    )
    session.add(workbook)
    session.flush()
    return workbook, True


def primary_sheet(workbook: Workbook) -> Workbook:
    root = workbook.parent or workbook
    for item in (root, *list(root.sheets)):
        if item.is_primary:
            return item
    return root


def sheet_is_frozen(workbook: Workbook) -> bool:
    return bool(workbook.is_issued or workbook.is_base)


def base_sheet_title(now: datetime | None = None) -> str:
    return f"База ({(now or datetime.now()).strftime('%d.%m.%Y')})"


def issued_sheet_title(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%d.%m.%Y")


def is_placeholder_main_name(name: str) -> bool:
    return (name or "").strip().casefold() in PLACEHOLDER_MAIN_NAMES


def working_sheet(workbook: Workbook) -> Workbook:
    root = workbook.parent or workbook
    for item in (root, *list(root.sheets)):
        if item.is_primary and not item.is_base:
            return item
    return primary_sheet(workbook)


def last_issued_sheet(sheets: list[Workbook]) -> Workbook | None:
    issued = [item for item in sheets if item.is_issued and not item.is_base]
    if not issued:
        return None
    return max(
        issued,
        key=lambda item: (_aware(item.created_at) or datetime.min.replace(tzinfo=timezone.utc), item.sheet_order),
    )


def order_project_sheets(sheets: list[Workbook]) -> list[Workbook]:
    main = next((item for item in sheets if item.is_primary and not item.is_base), None)
    if main is None:
        main = next((item for item in sheets if item.is_primary), sheets[0] if sheets else None)
    base = next((item for item in sheets if item.is_base), None)
    issued = sorted(
        [item for item in sheets if item.is_issued and not item.is_base and item is not main],
        key=lambda item: (_aware(item.created_at) or datetime.min.replace(tzinfo=timezone.utc), item.sheet_order),
    )
    seen = {item.id for item in [main, base, *issued] if item is not None}
    rest = [item for item in sheets if item.id not in seen]
    ordered = [item for item in [main, base, *issued, *rest] if item is not None]
    for order, item in enumerate(ordered):
        item.sheet_order = order
    return ordered


def sheet_brief(workbook: Workbook) -> dict:
    return {
        "id": workbook.id,
        "name": workbook.sheet_name,
        "order": workbook.sheet_order,
        "is_primary": workbook.is_primary,
        "is_issued": bool(workbook.is_issued),
        "issued_kind": normalize_issued_kind(getattr(workbook, "issued_kind", None), bool(workbook.is_issued)),
        "is_base": bool(workbook.is_base),
        "show_change_highlight": bool(workbook.show_change_highlight),
    }


def _snapshot_payload(cells: list[Cell]) -> str:
    rows = []
    for cell in cells:
        rows.append(
            {
                "parameter_key": cell.parameter_key,
                "column_key": cell.column_key,
                "value": cell.value,
                "status": cell.status,
                "hyperlink": cell.hyperlink,
                "locked": bool(cell.locked),
                "unified": bool(cell.unified),
                "excel_highlight": bool(cell.excel_highlight),
                "updated_at": _iso(cell.updated_at),
                "updated_by": cell.updated_by,
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def cells_from_issued_snapshot(workbook: Workbook) -> list[Cell]:
    try:
        raw = json.loads(workbook.issued_snapshot_json or "[]")
    except json.JSONDecodeError:
        raw = []
    cells: list[Cell] = []
    for item in raw:
        stamp = item.get("updated_at")
        cells.append(
            Cell(
                id=_new_id(),
                workbook_id=workbook.id,
                parameter_key=item["parameter_key"],
                column_key=item["column_key"],
                value=item.get("value"),
                draft_value=None,
                status=item.get("status") or "initial",
                hyperlink=item.get("hyperlink"),
                locked=bool(item.get("locked")),
                unified=bool(item.get("unified")),
                excel_highlight=bool(item.get("excel_highlight")),
                updated_at=datetime.fromisoformat(stamp) if stamp else None,
                updated_by=item.get("updated_by"),
            )
        )
    return cells


def _issued_source_cells(workbook: Workbook) -> list[Cell]:
    if primary_sheet(workbook).id == workbook.id:
        return list(workbook.cells)
    merged = dict(_base_cells(workbook))
    for cell in workbook.cells:
        merged[(cell.parameter_key, cell.column_key)] = cell
    return list(merged.values())


def freeze_as_issued(workbook: Workbook, issued_kind: str | None = None) -> None:
    session = object_session(workbook)
    if session is not None:
        session.flush()
        session.expire(workbook, ["cells"])
    workbook.issued_snapshot_json = _snapshot_payload(_issued_source_cells(workbook))
    workbook.is_issued = True
    workbook.issued_kind = normalize_issued_kind(issued_kind, True)
    workbook.is_base = False
    workbook.show_change_highlight = False


def reset_working_colors(session: Session, workbook: Workbook) -> None:
    for cell in list(workbook.cells):
        cell.excel_highlight = False
        if cell.status in {"confirmed", "triangle"}:
            cell.status = "initial" if cell.value else "empty"
    session.flush()


def set_sheet_issued(
    session: Session,
    workbook: Workbook,
    issued: bool,
    username: str,
    issued_kind: str | None = None,
) -> Workbook:
    root = workbook.parent or workbook
    if all(item.id != workbook.id for item in list_sheet_workbooks(session, root)):
        raise ValueError("Лист не найден в проекте")
    if workbook.is_primary:
        raise ValueError("Основную таблицу нельзя пометить как выданную версию. Используйте «Выдать версию» в отчёте")
    if workbook.is_base:
        raise ValueError("Базовый лист уже зафиксирован и недоступен как выданная версия")
    if issued and any(cell.status == "draft" for cell in workbook.cells):
        raise ValueError("Сначала сохраните или отмените черновики")
    if issued:
        kind = normalize_issued_kind(issued_kind, True)
        if issued_kind not in (None, "") and issued_kind not in ISSUED_KIND_LABELS:
            raise ValueError("Выберите тип выдачи: Предварительные данные, Конечные данные или Обновление")
        if workbook.is_issued:
            workbook.issued_kind = kind
            summary = f"Тип выдачи листа «{workbook.sheet_name}»: {issued_kind_label(kind)}"
        else:
            freeze_as_issued(workbook, kind)
            summary = f"Лист «{workbook.sheet_name}» отмечен как выданная версия ({issued_kind_label(kind)})"
    else:
        workbook.is_issued = False
        workbook.issued_kind = ""
        workbook.issued_snapshot_json = "[]"
        workbook.show_change_highlight = True
        compact_sheet(session, workbook)
        summary = f"С листа «{workbook.sheet_name}» снята отметка выданной версии"
    workbook.updated_at = _now()
    root.updated_at = _now()
    add_audit(
        session,
        actor=username,
        action="sheet_issued" if issued else "sheet_issue_cleared",
        workbook=root,
        old_value=workbook.sheet_name,
        new_value="выдана" if issued else None,
        summary=summary,
    )
    session.flush()
    return workbook


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _in_period(stamp: datetime | None, history_after: datetime | None) -> bool:
    if history_after is None:
        return True
    current = _aware(stamp)
    if current is None:
        return False
    return current > history_after


def _copy_period_history(
    session: Session,
    source: Cell,
    target: Cell,
    history_after: datetime | None,
) -> bool:
    copied = False
    for change in sorted(source.changes, key=lambda item: item.created_at):
        if not _in_period(change.created_at, history_after):
            continue
        session.add(
            CellChange(
                id=_new_id(),
                cell_id=target.id,
                author=change.author,
                created_at=change.created_at,
                old_value=change.old_value,
                new_value=change.new_value,
                comment=change.comment,
                user_journal=change.user_journal,
            )
        )
        copied = True
    return copied


def snapshot_working_sheet(
    session: Session,
    source: Workbook,
    name: str,
    username: str,
    *,
    history_after: datetime | None = None,
) -> Workbook:
    from src.services.workbook_import import copy_sheet

    clone = copy_sheet(session, source, name, username, include_values=False)
    stored = {(item.parameter_key, item.column_key): item for item in source.cells}
    moment = _now()
    for cell in effective_cells(source):
        if not (cell.value or cell.draft_value or cell.hyperlink):
            continue
        persistent = stored.get((cell.parameter_key, cell.column_key))
        period_changed = bool(cell.excel_highlight) or cell.status in {"confirmed", "triangle"}
        if persistent is not None:
            period_changed = (
                period_changed
                or _in_period(persistent.updated_at, history_after)
                or any(_in_period(change.created_at, history_after) for change in persistent.changes)
            )
        clone_cell = Cell(
            id=_new_id(),
            workbook_id=clone.id,
            parameter_key=cell.parameter_key,
            column_key=cell.column_key,
            value=cell.value,
            draft_value=None,
            status="initial" if cell.value else "empty",
            hyperlink=cell.hyperlink,
            locked=bool(cell.locked),
            unified=bool(cell.unified),
            excel_highlight=bool(period_changed),
            updated_by=username,
            updated_at=moment,
        )
        session.add(clone_cell)
        session.flush()
        if persistent is not None:
            _copy_period_history(session, persistent, clone_cell, history_after)
    session.flush()
    return clone


def issue_version(
    session: Session,
    workbook: Workbook,
    username: str,
    issued_kind: str | None = None,
) -> tuple[list[Workbook], Workbook]:
    root = workbook.parent or workbook
    sheets = list_sheet_workbooks(session, root)
    main = working_sheet(root)
    if any(cell.status == "draft" for cell in main.cells):
        raise ValueError("Сначала сохраните или отмените черновики основной таблицы")
    previous = last_issued_sheet(sheets)
    history_after = _aware(previous.updated_at or previous.created_at) if previous is not None else None
    title = _unique_sheet_name(issued_sheet_title(), sheets, "")
    if issued_kind not in (None, "") and issued_kind not in ISSUED_KIND_LABELS:
        raise ValueError("Выберите тип выдачи: Предварительные данные, Конечные данные или Обновление")
    kind = normalize_issued_kind(issued_kind, True)
    issued = snapshot_working_sheet(session, main, title, username, history_after=history_after)
    freeze_as_issued(issued, kind)
    issued_at = _now()
    issued.created_at = issued_at
    issued.updated_at = issued_at
    reset_working_colors(session, main)
    main.updated_at = issued_at
    root.updated_at = issued_at
    add_audit(
        session,
        actor=username,
        action="version_issued",
        workbook=root,
        old_value=previous.sheet_name if previous else None,
        new_value=issued.sheet_name,
        summary=f"Выдана версия «{issued.sheet_name}» ({issued_kind_label(kind)})",
    )
    session.flush()
    ordered = order_project_sheets(list_sheet_workbooks(session, root))
    session.flush()
    return ordered, issued


def _unique_sheet_name(name: str, sheets: list[Workbook], current_id: str) -> str:
    taken = {item.sheet_name.casefold() for item in sheets if item.id != current_id}
    candidate = name[:255]
    suffix = 2
    while candidate.casefold() in taken:
        candidate = f"{name} {suffix}"[:255]
        suffix += 1
    return candidate


def _replace_base_cells(session: Session, target: Workbook, source: Workbook, username: str) -> None:
    stale_ids = [cell.id for cell in list(target.cells)]
    if stale_ids:
        session.query(CellChange).filter(CellChange.cell_id.in_(stale_ids)).delete(synchronize_session=False)
        for cell in list(target.cells):
            session.delete(cell)
        session.flush()
        session.expire(target, ["cells"])
    stored = {(item.parameter_key, item.column_key): item for item in source.cells}
    moment = _now()
    for cell in effective_cells(source):
        if not (cell.value or cell.draft_value or cell.hyperlink):
            continue
        clone_cell = Cell(
            id=_new_id(),
            workbook_id=target.id,
            parameter_key=cell.parameter_key,
            column_key=cell.column_key,
            value=cell.value,
            draft_value=None,
            status="initial" if cell.value else "empty",
            hyperlink=cell.hyperlink,
            locked=bool(cell.locked),
            unified=bool(cell.unified),
            excel_highlight=bool(cell.excel_highlight),
            updated_by=username,
            updated_at=moment,
        )
        session.add(clone_cell)
        session.flush()
        persistent = stored.get((cell.parameter_key, cell.column_key))
        if persistent is not None:
            copy_cell_changes(session, persistent, clone_cell)
    session.flush()
    session.refresh(target)
    target.issued_snapshot_json = _snapshot_payload(list(target.cells))
    target.is_base = True
    target.is_issued = False
    target.issued_kind = ""
    target.is_primary = False
    target.show_change_highlight = False


def set_base_sheet(session: Session, workbook: Workbook, username: str) -> list[Workbook]:
    root = workbook.parent or workbook
    sheets = list_sheet_workbooks(session, root)
    if all(item.id != workbook.id for item in sheets):
        raise ValueError("Лист не найден в проекте")
    if any(cell.status == "draft" for cell in workbook.cells):
        raise ValueError("Сначала сохраните или отмените черновики")
    previous = next((item for item in sheets if item.is_base), None)
    title = _unique_sheet_name(base_sheet_title(), sheets, previous.id if previous else "")
    if previous is None:
        from src.services.workbook_import import copy_sheet

        previous = copy_sheet(session, workbook, title, username, include_values=False)
        sheets.append(previous)
    previous.sheet_name = title
    _replace_base_cells(session, previous, workbook, username)
    workbook.updated_at = _now()
    root.updated_at = _now()
    add_audit(
        session,
        actor=username,
        action="sheet_base_assigned",
        workbook=root,
        old_value=None,
        new_value=previous.sheet_name,
        summary=f"Лист «{previous.sheet_name}» назначен базовым по срезу «{workbook.sheet_name}»",
    )
    session.flush()
    return order_project_sheets(list_sheet_workbooks(session, root))


def set_change_highlight(session: Session, workbook: Workbook, enabled: bool) -> Workbook:
    root = workbook.parent or workbook
    if all(item.id != workbook.id for item in list_sheet_workbooks(session, root)):
        raise ValueError("Лист не найден в проекте")
    if workbook.is_issued or workbook.is_base:
        raise ValueError("Оранжевую подсветку включают на основной таблице")
    if not workbook.is_primary:
        raise ValueError("Оранжевую подсветку включают на основной таблице")
    workbook.show_change_highlight = bool(enabled)
    workbook.updated_at = _now()
    root.updated_at = _now()
    session.flush()
    return workbook


def clear_excel_highlight(session: Session, workbook: Workbook) -> int:
    root = workbook.parent or workbook
    cleared = 0
    for sheet in list_sheet_workbooks(session, root):
        for cell in list(sheet.cells):
            if cell.excel_highlight:
                cell.excel_highlight = False
                cleared += 1
        if not sheet_is_frozen(sheet):
            continue
        try:
            raw = json.loads(sheet.issued_snapshot_json or "[]")
        except json.JSONDecodeError:
            continue
        changed = False
        for item in raw:
            if item.get("excel_highlight"):
                item["excel_highlight"] = False
                changed = True
        if changed:
            sheet.issued_snapshot_json = json.dumps(raw, ensure_ascii=False)
    session.flush()
    return cleared


def _plain(value: str | None) -> str:
    return "" if value is None else str(value)


def cell_matches_base(cell: Cell, base: Cell | None) -> bool:
    if cell.draft_value not in (None, ""):
        return False
    return (
        _plain(cell.value) == _plain(base.value if base else None)
        and _plain(cell.hyperlink) == _plain(base.hyperlink if base else None)
        and bool(cell.unified) == bool(base.unified if base else False)
        and bool(cell.locked) == bool(base.locked if base else False)
    )


def _origin_cells(workbook: Workbook) -> list[Cell]:
    if sheet_is_frozen(workbook):
        return cells_from_issued_snapshot(workbook)
    return list(workbook.cells)


def _base_cells(workbook: Workbook) -> dict[tuple[str, str], Cell]:
    primary = primary_sheet(workbook)
    if primary.id == workbook.id:
        return {}
    return {(cell.parameter_key, cell.column_key): cell for cell in _origin_cells(primary)}


def effective_cells(workbook: Workbook) -> list[Cell]:
    if sheet_is_frozen(workbook):
        return cells_from_issued_snapshot(workbook)
    primary = primary_sheet(workbook)
    if primary.id == workbook.id:
        return list(workbook.cells)
    merged = {(cell.parameter_key, cell.column_key): cell for cell in _origin_cells(primary)}
    for cell in workbook.cells:
        key = (cell.parameter_key, cell.column_key)
        if not cell_matches_base(cell, merged.get(key)):
            merged[key] = cell
    return list(merged.values())


def compact_sheet(session: Session, workbook: Workbook) -> None:
    if sheet_is_frozen(workbook):
        return
    primary = primary_sheet(workbook)
    if primary.id == workbook.id:
        return
    base = {(cell.parameter_key, cell.column_key): cell for cell in primary.cells}
    stale = [
        cell
        for cell in list(workbook.cells)
        if cell_matches_base(cell, base.get((cell.parameter_key, cell.column_key)))
    ]
    if not stale:
        return
    ids = [cell.id for cell in stale]
    session.query(CellChange).filter(CellChange.cell_id.in_(ids)).delete(synchronize_session=False)
    for cell in stale:
        session.delete(cell)
    session.flush()
    session.expire(workbook, ["cells"])


def release_if_inherited(session: Session, workbook: Workbook, cell: Cell) -> Cell:
    if primary_sheet(workbook).id == workbook.id:
        return cell
    base = _base_cells(workbook).get((cell.parameter_key, cell.column_key))
    if not cell_matches_base(cell, base):
        return cell
    session.expunge(cell)
    session.query(CellChange).filter(CellChange.cell_id == cell.id).delete(synchronize_session=False)
    session.query(Cell).filter(Cell.id == cell.id).delete(synchronize_session=False)
    session.flush()
    session.expire(workbook, ["cells"])
    return base if base is not None else cell


def _check_sheet_conflict(workbook: Workbook, cell: Cell, expected_updated_at: str | None) -> None:
    if cell.updated_at is None and primary_sheet(workbook).id != workbook.id:
        base = _base_cells(workbook).get((cell.parameter_key, cell.column_key))
        base_at = _iso(base.updated_at) if base is not None else None
        if expected_updated_at in (None, "") or expected_updated_at == base_at:
            return
        if base is not None:
            raise CellConflict(_cell_conflict_payload(base))
    _check_conflict(cell, expected_updated_at)


def get_or_create_cell(session: Session, workbook: Workbook, parameter_key: str, column_key: str) -> Cell:
    cell = (
        session.query(Cell)
        .filter(
            Cell.workbook_id == workbook.id,
            Cell.parameter_key == parameter_key,
            Cell.column_key == column_key,
        )
        .first()
    )
    if cell:
        return cell
    base = _base_cells(workbook).get((parameter_key, column_key))
    cell = Cell(
        id=_new_id(),
        workbook_id=workbook.id,
        parameter_key=parameter_key,
        column_key=column_key,
        value=base.value if base is not None else None,
        status=base.status if base is not None and base.status else "empty",
        hyperlink=base.hyperlink if base is not None else None,
        locked=bool(base.locked) if base is not None else False,
        unified=bool(base.unified) if base is not None else False,
    )
    try:
        with session.begin_nested():
            session.add(cell)
            session.flush()
        return cell
    except IntegrityError:
        existing = (
            session.query(Cell)
            .filter(
                Cell.workbook_id == workbook.id,
                Cell.parameter_key == parameter_key,
                Cell.column_key == column_key,
            )
            .first()
        )
        if existing is None:
            raise
        return existing


def _cell_conflict_payload(cell: Cell) -> dict:
    return {
        "parameter_key": cell.parameter_key,
        "column_key": cell.column_key,
        "updated_by": cell.updated_by,
        "updated_at": _iso(cell.updated_at),
        "value": cell.value,
        "draft_value": cell.draft_value,
        "display": _display(cell),
    }


def _check_conflict(cell: Cell, expected_updated_at: str | None) -> None:
    current = _iso(cell.updated_at)
    if expected_updated_at is None or expected_updated_at == "":
        return
    if current != expected_updated_at:
        raise CellConflict(_cell_conflict_payload(cell))


def _update_cell_if_unchanged(
    session: Session,
    cell: Cell,
    values: dict,
    *,
    refresh: bool = True,
    defer_flush: bool = False,
) -> None:
    query = session.query(Cell).filter(Cell.id == cell.id)
    query = query.filter(
        Cell.updated_at.is_(None) if cell.updated_at is None else Cell.updated_at == cell.updated_at
    )
    if defer_flush:
        with session.no_autoflush:
            updated_count = query.update(values, synchronize_session=False)
    else:
        updated_count = query.update(values, synchronize_session=False)
    if updated_count != 1:
        session.expire(cell)
        session.refresh(cell)
        raise CellConflict(_cell_conflict_payload(cell))
    if refresh:
        session.expire(cell)
        session.refresh(cell)
    else:
        for key, value in values.items():
            set_committed_value(cell, key, value)


def _ensure_editable(
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    cell: Cell | None = None,
    *,
    allow_unified: bool = False,
) -> None:
    param = resolve_parameter(workbook, parameter_key)
    if not param or param.get("row_kind") not in {"editable"}:
        raise ValueError("Ячейка недоступна для редактирования")
    if column_key not in {item["key"] for item in workbook_columns(workbook)}:
        raise ValueError("Неизвестная колонка")
    if cell and cell.locked:
        raise ValueError("Ячейка заблокирована правилом унификации")
    if cell and cell.unified and not allow_unified:
        raise ValueError("Ячейка помечена как унифицированная и недоступна для изменения")


def set_cell_unification(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    username: str,
    unified: bool,
    expected_updated_at: str | None = None,
) -> Cell:
    cell = get_or_create_cell(session, workbook, parameter_key, column_key)
    _ensure_editable(workbook, parameter_key, column_key)
    _check_sheet_conflict(workbook, cell, expected_updated_at)
    if bool(cell.unified) == unified:
        return cell
    now = _now()
    _update_cell_if_unchanged(
        session,
        cell,
        {"unified": unified, "updated_at": now, "updated_by": username},
    )
    workbook.updated_at = now
    session.flush()
    return cell


def _saved_cell_status(session: Session, cell: Cell) -> str:
    if not cell.value:
        return "empty"
    last_change = (
        session.query(CellChange)
        .filter(CellChange.cell_id == cell.id)
        .order_by(CellChange.created_at.desc())
        .first()
    )
    if (
        last_change
        and last_change.new_value == cell.value
        and last_change.comment != PRIMARY_ORIGIN_COMMENT
        and not (last_change.comment or "").startswith(EXCEL_SHEET_COMMENT_PREFIX)
    ):
        return "confirmed"
    return "initial"


def set_draft(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    value: str | None,
    username: str,
    hyperlink: str | None = None,
    expected_updated_at: str | None = None,
) -> Cell:
    cell = get_or_create_cell(session, workbook, parameter_key, column_key)
    _ensure_editable(workbook, parameter_key, column_key, cell)
    _check_sheet_conflict(workbook, cell, expected_updated_at)
    if value is not None:
        value = normalize_decimal_commas(value)
    next_status = _saved_cell_status(session, cell) if (value or "") == (cell.value or "") else "draft"
    updates = {
        "draft_value": None if next_status != "draft" else value,
        "status": next_status,
        "updated_at": _now(),
        "updated_by": username,
    }
    if hyperlink is not None:
        updates["hyperlink"] = hyperlink
    _update_cell_if_unchanged(session, cell, updates)
    workbook.updated_at = _now()
    session.flush()
    return release_if_inherited(session, workbook, cell)


def _ensure_primary_origin(session: Session, workbook: Workbook, cell: Cell) -> None:
    if primary_sheet(workbook).id == workbook.id:
        return
    base = _base_cells(workbook).get((cell.parameter_key, cell.column_key))
    if base is None or not _plain(base.value):
        return
    already = session.query(CellChange.id).filter(CellChange.cell_id == cell.id).first()
    if already:
        return
    moment = _now()
    origin_at = base.updated_at or (moment - timedelta(seconds=1))
    if origin_at.tzinfo is None:
        origin_at = origin_at.replace(tzinfo=timezone.utc)
    if origin_at >= moment:
        origin_at = moment - timedelta(seconds=1)
    session.add(
        CellChange(
            id=_new_id(),
            cell_id=cell.id,
            author=base.updated_by or "Основной лист",
            created_at=origin_at,
            old_value=None,
            new_value=base.value,
            comment=PRIMARY_ORIGIN_COMMENT,
        )
    )


def copy_cell_changes(session: Session, source: Cell, target: Cell) -> None:
    for change in sorted(source.changes, key=lambda item: item.created_at):
        session.add(
            CellChange(
                id=_new_id(),
                cell_id=target.id,
                author=change.author,
                created_at=change.created_at,
                old_value=change.old_value,
                new_value=change.new_value,
                comment=change.comment,
                user_journal=change.user_journal,
            )
        )


def confirm_cell(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    username: str,
    comment: str,
    value: str | None = None,
    hyperlink: str | None = None,
    expected_updated_at: str | None = None,
    system: bool = False,
    existing_cell: Cell | None = None,
    user_journal: bool = True,
) -> Cell:
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("Комментарий обязателен")
    cell = existing_cell if existing_cell is not None else get_or_create_cell(
        session, workbook, parameter_key, column_key
    )
    if not system:
        _ensure_editable(workbook, parameter_key, column_key, cell)
        _check_sheet_conflict(workbook, cell, expected_updated_at)
    new_value = value if value is not None else cell.draft_value
    if new_value is None:
        raise ValueError("Нет значения для сохранения")
    new_value = normalize_decimal_commas(new_value)
    old_value = cell.value
    previous_author = cell.updated_by
    _ensure_primary_origin(session, workbook, cell)
    change = CellChange(
        id=_new_id(),
        cell_id=cell.id,
        author=username,
        created_at=_now(),
        old_value=old_value,
        new_value=new_value,
        comment=comment,
        user_journal=user_journal,
    )
    updates = {
        "value": new_value,
        "draft_value": None,
        "status": "confirmed",
        "excel_highlight": False,
        "updated_at": _now(),
        "updated_by": username,
    }
    if hyperlink is not None:
        updates["hyperlink"] = hyperlink
    defer_flush = system and existing_cell is not None
    _update_cell_if_unchanged(
        session,
        cell,
        updates,
        refresh=not defer_flush,
        defer_flush=defer_flush,
    )
    session.add(change)
    workbook.updated_at = _now()
    if not defer_flush:
        session.flush()
    cell.last_change_id = change.id
    if not system:
        for recipient in recipients_for_cell_change(session, workbook, cell, username, previous_author):
            add_notification(
                session,
                recipient=recipient,
                author=username,
                workbook=workbook,
                parameter_key=parameter_key,
                column_key=column_key,
            )
    if not system:
        apply_rules(session, workbook, parameter_key, column_key, username)
        session.flush()
        still = session.get(Cell, cell.id)
        if still is None:
            cell = _base_cells(workbook).get((parameter_key, column_key)) or cell
        else:
            cell = release_if_inherited(session, workbook, still)
    return cell


def add_cell_comment(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    username: str,
    comment: str,
    expected_updated_at: str | None = None,
) -> Cell:
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("Комментарий обязателен")
    cell = get_or_create_cell(session, workbook, parameter_key, column_key)
    _ensure_editable(workbook, parameter_key, column_key, cell, allow_unified=True)
    _check_sheet_conflict(workbook, cell, expected_updated_at)
    now = _now()
    _ensure_primary_origin(session, workbook, cell)
    change = CellChange(
        id=_new_id(),
        cell_id=cell.id,
        author=username,
        created_at=now,
        old_value=cell.value,
        new_value=cell.value,
        comment=comment,
    )
    _update_cell_if_unchanged(session, cell, {"updated_at": now, "updated_by": username})
    session.add(change)
    workbook.updated_at = now
    session.flush()
    cell.last_change_id = change.id
    session.flush()
    return cell


def restore_session(
    session: Session,
    workbook: Workbook,
    username: str,
    cells: list[dict],
    extra_parameters: list | None = None,
    parameter_overrides: dict | None = None,
    deleted_parameters: list | None = None,
    extra_columns: list | None = None,
    column_overrides: dict | None = None,
    deleted_columns: list[str] | None = None,
    remove_change_ids: list[str] | None = None,
    clear_keys: list[dict] | None = None,
    add_changes: list[dict] | None = None,
) -> Workbook:
    if extra_columns is not None:
        _save_json(workbook, "extra_columns_json", extra_columns)
    if column_overrides is not None:
        _save_json(workbook, "column_overrides_json", column_overrides)
    if deleted_columns is not None:
        _save_json(workbook, "deleted_columns_json", deleted_columns)
    if extra_parameters is not None:
        _save_json(workbook, "extra_parameters_json", extra_parameters)
    if parameter_overrides is not None:
        _save_json(workbook, "parameter_overrides_json", parameter_overrides)
    if deleted_parameters is not None:
        _save_json(workbook, "deleted_parameters_json", deleted_parameters)
    for item in cells:
        cell = get_or_create_cell(session, workbook, item["parameter_key"], item["column_key"])
        if cell.unified:
            continue
        cell.value = item.get("value")
        cell.draft_value = item.get("draft_value")
        cell.status = item.get("status") or ("confirmed" if cell.value else "empty")
        cell.hyperlink = item.get("hyperlink")
        cell.locked = bool(item.get("locked"))
        cell.excel_highlight = bool(item.get("excel_highlight"))
        cell.updated_by = username
        cell.updated_at = _now()
    for item in clear_keys or []:
        cell = get_or_create_cell(session, workbook, item["parameter_key"], item["column_key"])
        if cell.unified:
            continue
        cell.value = None
        cell.draft_value = None
        cell.status = "empty"
        cell.hyperlink = None
        cell.locked = False
        cell.excel_highlight = False
        cell.updated_by = username
        cell.updated_at = _now()
    for change_id in remove_change_ids or []:
        change = session.get(CellChange, change_id)
        if change is not None:
            session.delete(change)
    for item in add_changes or []:
        cell = get_or_create_cell(session, workbook, item["parameter_key"], item["column_key"])
        change = CellChange(
            id=item.get("id") or _new_id(),
            cell_id=cell.id,
            author=item.get("author") or username,
            old_value=item.get("old_value"),
            new_value=item.get("new_value"),
            comment=item.get("comment") or "",
        )
        session.add(change)
    workbook.updated_at = _now()
    session.flush()
    compact_sheet(session, workbook)
    session.expire(workbook)
    return workbook


def discard_draft(session: Session, workbook: Workbook, parameter_key: str, column_key: str) -> Cell:
    cell = get_or_create_cell(session, workbook, parameter_key, column_key)
    cell.draft_value = None
    cell.status = _saved_cell_status(session, cell)
    workbook.updated_at = _now()
    session.flush()
    return release_if_inherited(session, workbook, cell)


def unsaved_cells(session: Session, workbook: Workbook) -> list[dict]:
    rows = []
    for cell in workbook.cells:
        if cell.status != "draft":
            continue
        param = resolve_parameter(workbook, cell.parameter_key)
        col = resolve_column(workbook, cell.column_key)
        rows.append(
            {
                "parameter_key": cell.parameter_key,
                "column_key": cell.column_key,
                "parameter_label": param["label"] if param else cell.parameter_key,
                "column_label": col["label"] if col else cell.column_key,
                "draft_value": cell.draft_value,
                "value": cell.value,
            }
        )
    return rows


def _history_cell(session: Session, workbook: Workbook, parameter_key: str, column_key: str) -> Cell | None:
    cell = (
        session.query(Cell)
        .filter(
            Cell.workbook_id == workbook.id,
            Cell.parameter_key == parameter_key,
            Cell.column_key == column_key,
        )
        .first()
    )
    if sheet_is_frozen(workbook):
        return cell
    base = _base_cells(workbook).get((parameter_key, column_key))
    if cell is None or cell_matches_base(cell, base):
        return base
    return cell


def cell_history(session: Session, workbook: Workbook, parameter_key: str, column_key: str) -> list[CellChange]:
    cell = _history_cell(session, workbook, parameter_key, column_key)
    if not cell:
        return []
    return sorted(cell.changes, key=lambda item: item.created_at)


def _cell_compare_value(workbook: Workbook, parameter_key: str, column_key: str) -> str | None:
    for cell in effective_cells(workbook):
        if cell.parameter_key == parameter_key and cell.column_key == column_key:
            return _display(cell)
    return None


def _sheet_value_map(workbook: Workbook) -> dict[tuple[str, str], str | None]:
    return {(cell.parameter_key, cell.column_key): _display(cell) for cell in effective_cells(workbook)}


def _resolved_compare_targets(
    session: Session,
    workbook: Workbook,
    sheet_ids: list[str] | None,
    range_from: str | None,
    range_to: str | None,
    combine: str,
) -> tuple[list[Workbook], list[Workbook], str]:
    sheets = list_sheet_workbooks(session, workbook)
    by_id = {item.id: item for item in sheets}
    mode = "and" if combine == "and" else "or"
    target_ids = combine_compare_targets(
        [item.id for item in sheets],
        workbook.id,
        sheet_ids or [],
        range_from,
        range_to,
        mode,
    )
    return sheets, [by_id[sheet_id] for sheet_id in target_ids], mode


def compare_cell_across_sheets(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    *,
    sheet_ids: list[str] | None = None,
    range_from: str | None = None,
    range_to: str | None = None,
    combine: str = "or",
) -> dict:
    _sheets, targets, mode = _resolved_compare_targets(
        session, workbook, sheet_ids, range_from, range_to, combine
    )
    current_value = _cell_compare_value(workbook, parameter_key, column_key)
    rows = []
    for sheet in targets:
        value = _cell_compare_value(sheet, parameter_key, column_key)
        rows.append(
            {
                "sheet_id": sheet.id,
                "sheet_name": sheet.sheet_name,
                "value": value,
                "differs": values_differ(current_value, value),
            }
        )
    return {
        "parameter_key": parameter_key,
        "column_key": column_key,
        "combine": mode,
        "current": {
            "sheet_id": workbook.id,
            "sheet_name": workbook.sheet_name,
            "value": current_value,
            "differs": False,
        },
        "targets": rows,
        "differs_any": any(item["differs"] for item in rows),
        "differs_all": bool(rows) and all(item["differs"] for item in rows),
    }


def compare_sheet_across_sheets(
    session: Session,
    workbook: Workbook,
    *,
    sheet_ids: list[str] | None = None,
    range_from: str | None = None,
    range_to: str | None = None,
    combine: str = "or",
) -> dict:
    _sheets, targets, mode = _resolved_compare_targets(
        session, workbook, sheet_ids, range_from, range_to, combine
    )
    current_map = _sheet_value_map(workbook)
    target_maps = [(sheet, _sheet_value_map(sheet)) for sheet in targets]
    keys = set(current_map)
    for _sheet, values in target_maps:
        keys.update(values)
    payload = workbook_payload(session, workbook)
    by_key = {(cell["parameter_key"], cell["column_key"]): dict(cell) for cell in payload["cells"]}
    changed = 0
    for key in keys:
        parameter_key, column_key = key
        current_value = current_map.get(key)
        against = []
        for sheet, values in target_maps:
            other = values.get(key)
            if values_differ(current_value, other):
                against.append(
                    {
                        "sheet_id": sheet.id,
                        "sheet_name": sheet.sheet_name,
                        "value": other,
                        "differs": True,
                    }
                )
        cell = by_key.get(key) or {
            "parameter_key": parameter_key,
            "column_key": column_key,
            "value": current_value,
            "draft_value": None,
            "status": "empty",
            "hyperlink": None,
            "display": current_value,
            "locked": True,
            "unified": False,
            "updated_at": None,
            "updated_by": None,
            "options": options_for(parameter_key),
            "last_change_id": None,
        }
        cell["excel_highlight"] = False
        cell["compare_highlight"] = bool(against)
        cell["compare_against"] = against
        if against:
            changed += 1
        by_key[key] = cell
    payload["cells"] = list(by_key.values())
    payload["is_issued"] = True
    payload["show_change_highlight"] = True
    return {
        "combine": mode,
        "workbook": payload,
        "catalog": catalog_payload(workbook),
        "targets": [
            {"sheet_id": sheet.id, "sheet_name": sheet.sheet_name, "value": None, "differs": False}
            for sheet in targets
        ],
        "changed_count": changed,
    }


def latest_cell_comment(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
) -> str | None:
    cell = _history_cell(session, workbook, parameter_key, column_key)
    if cell is None:
        return None
    row = (
        session.query(CellChange.comment)
        .filter(CellChange.cell_id == cell.id, CellChange.comment != "")
        .order_by(CellChange.created_at.desc())
        .first()
    )
    return row[0] if row else None


def create_version(
    session: Session,
    workbook: Workbook,
    username: str,
    kind: str,
    description: str = "",
    snapshot: dict[str, dict[str, str | None]] | None = None,
) -> Version:
    version = Version(
        id=_new_id(),
        workbook_id=workbook.id,
        kind=kind,
        description=description,
        created_by=username,
        snapshot_json=json.dumps(snapshot if snapshot is not None else snapshot_cells(workbook), ensure_ascii=False),
    )
    session.add(version)
    session.flush()
    if kind != "triangle_import":
        add_audit(
            session,
            actor=username,
            action="report" if kind == "report_snapshot" else "version",
            workbook=workbook,
            comment=description,
            summary=description or kind,
        )
    return version


def restore_version(session: Session, workbook: Workbook, version: Version) -> Workbook:
    snapshot = json.loads(version.snapshot_json)
    active_columns = {item["key"] for item in workbook_columns(workbook)}
    existing = {(cell.parameter_key, cell.column_key): cell for cell in workbook.cells}
    for parameter_key, columns_map in snapshot.items():
        for column_key, value in columns_map.items():
            if column_key not in active_columns:
                continue
            cell = existing.get((parameter_key, column_key))
            if cell is None:
                cell = get_or_create_cell(session, workbook, parameter_key, column_key)
            if cell.unified:
                continue
            cell.value = value
            cell.draft_value = None
            cell.status = "confirmed" if value else "empty"
            cell.locked = False
    workbook.updated_at = _now()
    session.flush()
    return workbook


def add_stage_column(session: Session, workbook: Workbook, label: str, username: str = "") -> dict:
    current = extra_columns(workbook)
    item = {
        "key": f"s_custom_{uuid.uuid4().hex[:12]}",
        "label": label.strip(),
        "kind": "stage",
        "order": len(columns()) + len(current),
    }
    current.append(item)
    _save_json(workbook, "extra_columns_json", current)
    session.flush()
    if username:
        add_audit(
            session,
            actor=username,
            action="column_added",
            workbook=workbook,
            column_key=item["key"],
            new_value=item["label"],
            summary=f"Добавлен столбец «{item['label']}»",
        )
    return item


def update_column_label(session: Session, workbook: Workbook, key: str, label: str, username: str) -> dict:
    previous = next((item for item in workbook_columns(workbook) if item["key"] == key), None)
    if previous is None:
        raise ValueError("Столбец не найден")
    cleaned_label = label.strip()
    if not cleaned_label:
        raise ValueError("Укажите наименование столбца")
    overrides = column_overrides(workbook)
    overrides[key] = cleaned_label
    _save_json(workbook, "column_overrides_json", overrides)
    session.flush()
    add_audit(
        session,
        actor=username,
        action="column_changed",
        workbook=workbook,
        column_key=key,
        old_value=previous.get("label"),
        new_value=cleaned_label,
        summary=f"Столбец «{previous.get('label')}» → «{cleaned_label}»",
    )
    return {**previous, "label": cleaned_label}


def delete_column(session: Session, workbook: Workbook, key: str, username: str) -> None:
    previous = next((item for item in workbook_columns(workbook) if item["key"] == key), None)
    if previous is None:
        raise ValueError("Столбец не найден")
    extras = extra_columns(workbook)
    remaining_extras = [item for item in extras if item["key"] != key]
    if len(remaining_extras) != len(extras):
        _save_json(workbook, "extra_columns_json", remaining_extras)
    else:
        deleted = deleted_column_keys(workbook)
        deleted.add(key)
        _save_json(workbook, "deleted_columns_json", sorted(deleted))
    overrides = column_overrides(workbook)
    overrides.pop(key, None)
    _save_json(workbook, "column_overrides_json", overrides)
    session.flush()
    add_audit(
        session,
        actor=username,
        action="column_deleted",
        workbook=workbook,
        column_key=key,
        old_value=previous.get("label"),
        summary=f"Удалён столбец «{previous.get('label')}»",
    )


def add_parameter_row(
    session: Session,
    workbook: Workbook,
    label: str,
    group: str = "",
    unit: str | None = None,
    indent: int | None = None,
    row_kind: str = "editable",
    insert_after: str | None = None,
    username: str = "",
) -> dict:
    kind = row_kind if row_kind in {"editable", "section"} else "editable"
    level = 0 if kind == "section" else (indent if indent is not None else 1)
    current = extra_parameters(workbook)
    existing = workbook_parameters(workbook)
    key = f"p_custom_{len(existing) + 1}"
    after_index = next((index for index, item in enumerate(existing) if item["key"] == insert_after), len(existing) - 1)
    if existing and after_index >= 0:
        current_order = float(existing[after_index].get("order") or after_index)
        next_order = (
            float(existing[after_index + 1].get("order") or current_order + 2)
            if after_index + 1 < len(existing)
            else current_order + 2
        )
        order = (current_order + next_order) / 2
    else:
        order = float(len(existing))
    parent = existing[after_index] if existing and after_index >= 0 else None
    item = {
        "key": key,
        "excel_row": 0,
        "label": label.strip(),
        "label_raw": label.strip(),
        "group": group or (parent["key"] if parent and parent.get("row_kind") == "section" else (parent or {}).get("group") or "custom"),
        "indent": max(0, min(int(level), 2)),
        "row_kind": kind,
        "unit": unit if kind == "editable" else None,
        "order": order,
    }
    current.append(item)
    _save_json(workbook, "extra_parameters_json", current)
    session.flush()
    if username:
        add_audit(
            session,
            actor=username,
            action="parameter_added",
            workbook=workbook,
            parameter_key=key,
            new_value=item["label"],
            summary=f"Добавлен параметр «{item['label']}»",
        )
    return item


def update_parameter_row(
    session: Session,
    workbook: Workbook,
    key: str,
    username: str,
    label: str | None = None,
    unit: str | None = None,
    indent: int | None = None,
    group: str | None = None,
    row_kind: str | None = None,
) -> dict:
    current = extra_parameters(workbook)
    extra = next((item for item in current if item["key"] == key), None)
    previous = resolve_parameter(workbook, key)
    if previous is None:
        raise ValueError("Параметр не найден")
    patch: dict = {}
    if label is not None:
        patch["label"] = label.strip()
        patch["label_raw"] = label.strip()
    if unit is not None:
        patch["unit"] = unit.strip() or None
    if indent is not None:
        patch["indent"] = max(0, min(int(indent), 2))
    if group is not None:
        patch["group"] = group
    if row_kind in {"editable", "section"}:
        patch["row_kind"] = row_kind
        if row_kind == "section":
            patch["unit"] = None
    if extra is not None:
        extra.update(patch)
        _save_json(workbook, "extra_parameters_json", current)
        updated = extra
    else:
        overrides = parameter_overrides(workbook)
        merged = dict(overrides.get(key) or {})
        merged.update(patch)
        overrides[key] = merged
        _save_json(workbook, "parameter_overrides_json", overrides)
        updated = {**previous, **patch}
    session.flush()
    add_audit(
        session,
        actor=username,
        action="parameter_changed",
        workbook=workbook,
        parameter_key=key,
        old_value=previous.get("label"),
        new_value=updated.get("label"),
        summary=f"Параметр «{previous.get('label')}» → «{updated.get('label')}»",
    )
    return updated


def delete_parameter_row(session: Session, workbook: Workbook, key: str, username: str) -> None:
    previous = resolve_parameter(workbook, key)
    if previous is None:
        raise ValueError("Параметр не найден")
    extras = [item for item in extra_parameters(workbook) if item["key"] != key]
    if len(extras) != len(extra_parameters(workbook)):
        _save_json(workbook, "extra_parameters_json", extras)
    else:
        deleted = deleted_parameter_keys(workbook)
        deleted.add(key)
        _save_json(workbook, "deleted_parameters_json", sorted(deleted))
    session.flush()
    add_audit(
        session,
        actor=username,
        action="parameter_deleted",
        workbook=workbook,
        parameter_key=key,
        old_value=previous.get("label"),
        summary=f"Удалён параметр «{previous.get('label')}»",
    )


def apply_imported_values(
    session: Session,
    workbook: Workbook,
    values: dict[str, dict[str, str]],
    username: str,
    source_name: str,
) -> int:
    count = 0
    allowed = editable_keys(workbook)
    known_columns = {item["key"] for item in workbook_columns(workbook)}
    for parameter_key, column_map in values.items():
        if parameter_key not in allowed:
            continue
        for column_key, value in column_map.items():
            if column_key not in known_columns or value is None or str(value).strip() == "":
                continue
            cell = get_or_create_cell(session, workbook, parameter_key, column_key)
            if cell.unified:
                continue
            cell.value = str(value).strip()
            cell.draft_value = None
            cell.status = "initial"
            cell.updated_by = username
            cell.updated_at = _now()
            count += 1
    create_version(
        session,
        workbook,
        username,
        kind="triangle_import",
        description=f"Считывание треугольников: {source_name}",
    )
    add_audit(
        session,
        actor=username,
        action="imported",
        workbook=workbook,
        comment=source_name,
        summary=f"Импорт треугольников: {count} значений ({source_name})",
    )
    workbook.updated_at = _now()
    session.flush()
    return count


def apply_rules(
    session: Session,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
    username: str,
    user_journal: bool = True,
) -> None:
    source = get_or_create_cell(session, workbook, parameter_key, column_key)
    value = _display(source) or source.value
    matched = matching_rules(parameter_key, value)
    lock_now: set[str] = set()
    for rule in matched:
        lock_now.update(rule.get("lock") or [])
        for item in rule.get("copy") or []:
            src = get_or_create_cell(session, workbook, item["from"], column_key)
            dst = get_or_create_cell(session, workbook, item["to"], column_key)
            copied = _display(src) or src.value
            if copied and copied != dst.value and not dst.unified:
                dst.locked = False
                confirm_cell(
                    session,
                    workbook,
                    item["to"],
                    column_key,
                    username,
                    comment=f"Автоматически по правилу «{rule.get('id')}»",
                    value=copied,
                    system=True,
                    user_journal=user_journal,
                )
                dst = get_or_create_cell(session, workbook, item["to"], column_key)
            dst.locked = True
    if parameter_key == "r021":
        for key in all_lock_keys():
            cell = get_or_create_cell(session, workbook, key, column_key)
            cell.locked = key in lock_now
    session.flush()
    compact_sheet(session, workbook)


def add_notification(
    session: Session,
    *,
    recipient: str,
    author: str,
    workbook: Workbook,
    parameter_key: str,
    column_key: str,
) -> None:
    param = resolve_parameter(workbook, parameter_key)
    col = resolve_column(workbook, column_key)
    label = param["label"] if param else parameter_key
    col_label = col["label"] if col else column_key
    note = Notification(
        id=_new_id(),
        recipient=recipient,
        author=author,
        workbook_id=workbook.id,
        parameter_key=parameter_key,
        column_key=column_key,
        message=f"{author} изменил «{label}» / {col_label}",
        read=False,
    )
    session.add(note)
    session.flush()


def list_notifications(session: Session, username: str) -> list[Notification]:
    rows = session.query(Notification).filter(Notification.recipient == username).all()
    return sorted(rows, key=lambda item: item.created_at, reverse=True)


def mark_notification_read(session: Session, note_id: str, username: str) -> Notification | None:
    note = session.get(Notification, note_id)
    if note is None or note.recipient != username:
        return None
    note.read = True
    session.flush()
    return note


def workbook_payload(session: Session, workbook: Workbook) -> dict:
    compact_sheet(session, workbook)
    obj = workbook.object
    unsaved = unsaved_cells(session, workbook)
    return {
        "id": workbook.id,
        "object_id": workbook.object_id,
        "object": {
            "id": obj.id,
            "name": obj.name,
            "station": obj.station,
            "turbine": obj.turbine,
            "cylinder": obj.cylinder,
            "external_id": obj.external_id,
            "status": obj.status,
            "has_workbook": True,
            "workbook_id": (workbook.parent or workbook).id,
        },
        "created_at": workbook.created_at,
        "updated_at": workbook.updated_at,
        "created_by": workbook.created_by,
        "parent_workbook_id": workbook.parent_workbook_id,
        "sheet_name": workbook.sheet_name,
        "sheet_order": workbook.sheet_order,
        "is_primary": workbook.is_primary,
        "is_issued": bool(workbook.is_issued),
        "issued_kind": normalize_issued_kind(getattr(workbook, "issued_kind", None), bool(workbook.is_issued)),
        "is_base": bool(workbook.is_base),
        "show_change_highlight": bool(workbook.show_change_highlight),
        "cells": [cell_to_dict(cell, workbook) for cell in effective_cells(workbook)],
        "unsaved_count": len(unsaved),
        "report_notes": report_notes(workbook),
    }


def catalog_payload(workbook: Workbook | None = None) -> dict:
    params = []
    for item in workbook_parameters(workbook):
        row = dict(item)
        row["options"] = options_for(item["key"])
        params.append(row)
    cols = workbook_columns(workbook) if workbook is not None else columns()
    return {
        "columns": cols,
        "parameters": params,
        "extra_columns": extra_columns(workbook) if workbook is not None else [],
        "column_overrides": column_overrides(workbook) if workbook is not None else {},
        "deleted_columns": sorted(deleted_column_keys(workbook)) if workbook is not None else [],
        "extra_parameters": extra_parameters(workbook) if workbook is not None else [],
        "parameter_overrides": parameter_overrides(workbook) if workbook is not None else {},
        "deleted_parameters": sorted(deleted_parameter_keys(workbook)) if workbook is not None else [],
    }
