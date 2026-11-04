from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models import Cell, CellChange, Notification, ObjectItem, Version, Workbook
from src.catalog import column_by_key, columns, parameter_by_key, parameters
from src.services.journal import add_audit
from src.services.rules import all_lock_keys, matching_rules, options_for


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
    if cell.status == "draft" and cell.draft_value is not None:
        return cell.draft_value
    return cell.value


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


def workbook_columns(workbook: Workbook) -> list[dict]:
    return columns() + extra_columns(workbook)


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
        "updated_at": _iso(cell.updated_at),
        "updated_by": cell.updated_by,
        "options": options_for(param_key),
        "last_change_id": getattr(cell, "last_change_id", None),
    }


def snapshot_cells(workbook: Workbook) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for cell in workbook.cells:
        result.setdefault(cell.parameter_key, {})[cell.column_key] = cell.value
    return result


def hyperlinks_map(workbook: Workbook) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for cell in workbook.cells:
        if cell.hyperlink:
            result.setdefault(cell.parameter_key, {})[cell.column_key] = cell.hyperlink
    return result


def get_workbook(session: Session, workbook_id: str) -> Workbook | None:
    return session.get(Workbook, workbook_id)


def ensure_workbook(session: Session, object_item: ObjectItem, username: str) -> tuple[Workbook, bool]:
    existing = (
        session.query(Workbook)
        .filter(Workbook.object_id == object_item.id)
        .order_by(Workbook.created_at.desc())
        .first()
    )
    if existing:
        return existing, False
    workbook = Workbook(
        id=_new_id(),
        object_id=object_item.id,
        created_by=username,
        extra_columns_json="[]",
        extra_parameters_json="[]",
        parameter_overrides_json="{}",
        deleted_parameters_json="[]",
    )
    session.add(workbook)
    session.flush()
    return workbook, True


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
    cell = Cell(
        id=_new_id(),
        workbook_id=workbook.id,
        parameter_key=parameter_key,
        column_key=column_key,
        status="empty",
        locked=False,
    )
    session.add(cell)
    session.flush()
    return cell


def _check_conflict(cell: Cell, expected_updated_at: str | None) -> None:
    current = _iso(cell.updated_at)
    if expected_updated_at is None or expected_updated_at == "":
        return
    if current and current != expected_updated_at:
        raise CellConflict(
            {
                "parameter_key": cell.parameter_key,
                "column_key": cell.column_key,
                "updated_by": cell.updated_by,
                "updated_at": current,
                "value": cell.value,
                "draft_value": cell.draft_value,
                "display": _display(cell),
            }
        )


def _ensure_editable(workbook: Workbook, parameter_key: str, column_key: str, cell: Cell | None = None) -> None:
    param = resolve_parameter(workbook, parameter_key)
    if not param or param.get("row_kind") not in {"editable"}:
        raise ValueError("Ячейка недоступна для редактирования")
    if column_key not in {item["key"] for item in workbook_columns(workbook)}:
        raise ValueError("Неизвестная колонка")
    if cell and cell.locked:
        raise ValueError("Ячейка заблокирована правилом унификации")


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
    _check_conflict(cell, expected_updated_at)
    cell.draft_value = value
    if hyperlink is not None:
        cell.hyperlink = hyperlink
    if (value or "") == (cell.value or ""):
        cell.draft_value = None
        cell.status = "confirmed" if cell.value else "empty"
    else:
        cell.status = "draft"
    cell.updated_at = _now()
    cell.updated_by = username
    workbook.updated_at = _now()
    session.flush()
    return cell


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
) -> Cell:
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("Комментарий обязателен")
    cell = get_or_create_cell(session, workbook, parameter_key, column_key)
    if not system:
        _ensure_editable(workbook, parameter_key, column_key, cell)
        _check_conflict(cell, expected_updated_at)
    new_value = value if value is not None else cell.draft_value
    if new_value is None:
        raise ValueError("Нет значения для сохранения")
    old_value = cell.value
    previous_author = cell.updated_by
    cell.value = new_value
    cell.draft_value = None
    cell.status = "confirmed" if not cell.locked or system else "confirmed"
    if hyperlink is not None:
        cell.hyperlink = hyperlink
    change = CellChange(
        id=_new_id(),
        cell_id=cell.id,
        author=username,
        old_value=old_value,
        new_value=new_value,
        comment=comment,
    )
    session.add(change)
    cell.updated_at = _now()
    cell.updated_by = username
    workbook.updated_at = _now()
    session.flush()
    cell.last_change_id = change.id
    if not system and previous_author and previous_author != username:
        add_notification(
            session,
            recipient=previous_author,
            author=username,
            workbook=workbook,
            parameter_key=parameter_key,
            column_key=column_key,
        )
    if not system:
        apply_rules(session, workbook, parameter_key, column_key, username)
    return cell


def restore_session(
    session: Session,
    workbook: Workbook,
    username: str,
    cells: list[dict],
    extra_parameters: list | None = None,
    parameter_overrides: dict | None = None,
    deleted_parameters: list | None = None,
    remove_change_ids: list[str] | None = None,
    clear_keys: list[dict] | None = None,
    add_changes: list[dict] | None = None,
) -> Workbook:
    if extra_parameters is not None:
        _save_json(workbook, "extra_parameters_json", extra_parameters)
    if parameter_overrides is not None:
        _save_json(workbook, "parameter_overrides_json", parameter_overrides)
    if deleted_parameters is not None:
        _save_json(workbook, "deleted_parameters_json", deleted_parameters)
    for item in cells:
        cell = get_or_create_cell(session, workbook, item["parameter_key"], item["column_key"])
        cell.value = item.get("value")
        cell.draft_value = item.get("draft_value")
        cell.status = item.get("status") or ("confirmed" if cell.value else "empty")
        cell.hyperlink = item.get("hyperlink")
        cell.locked = bool(item.get("locked"))
        cell.updated_by = username
        cell.updated_at = _now()
    for item in clear_keys or []:
        cell = get_or_create_cell(session, workbook, item["parameter_key"], item["column_key"])
        cell.value = None
        cell.draft_value = None
        cell.status = "empty"
        cell.hyperlink = None
        cell.locked = False
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
    session.expire(workbook)
    return workbook


def discard_draft(session: Session, workbook: Workbook, parameter_key: str, column_key: str) -> Cell:
    cell = get_or_create_cell(session, workbook, parameter_key, column_key)
    cell.draft_value = None
    cell.status = "confirmed" if cell.value else "empty"
    workbook.updated_at = _now()
    session.flush()
    return cell


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


def cell_history(session: Session, workbook: Workbook, parameter_key: str, column_key: str) -> list[CellChange]:
    cell = (
        session.query(Cell)
        .filter(
            Cell.workbook_id == workbook.id,
            Cell.parameter_key == parameter_key,
            Cell.column_key == column_key,
        )
        .first()
    )
    if not cell:
        return []
    return sorted(cell.changes, key=lambda item: item.created_at, reverse=True)


def create_version(
    session: Session,
    workbook: Workbook,
    username: str,
    kind: str,
    description: str = "",
) -> Version:
    version = Version(
        id=_new_id(),
        workbook_id=workbook.id,
        kind=kind,
        description=description,
        created_by=username,
        snapshot_json=json.dumps(snapshot_cells(workbook), ensure_ascii=False),
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
    existing = {(cell.parameter_key, cell.column_key): cell for cell in workbook.cells}
    for parameter_key, columns_map in snapshot.items():
        for column_key, value in columns_map.items():
            cell = existing.get((parameter_key, column_key))
            if cell is None:
                cell = get_or_create_cell(session, workbook, parameter_key, column_key)
            cell.value = value
            cell.draft_value = None
            cell.status = "confirmed" if value else "empty"
            cell.locked = False
    workbook.updated_at = _now()
    session.flush()
    return workbook


def add_stage_column(session: Session, workbook: Workbook, label: str) -> dict:
    current = extra_columns(workbook)
    key = f"s_custom_{len(columns()) + len(current) + 1}"
    item = {"key": key, "label": label.strip(), "kind": "stage", "order": len(columns()) + len(current)}
    current.append(item)
    workbook.extra_columns_json = json.dumps(current, ensure_ascii=False)
    session.flush()
    return item


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
            cell.value = str(value).strip()
            cell.draft_value = None
            cell.status = "confirmed"
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


def apply_rules(session: Session, workbook: Workbook, parameter_key: str, column_key: str, username: str) -> None:
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
            if copied and copied != dst.value:
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
                )
                dst = get_or_create_cell(session, workbook, item["to"], column_key)
            dst.locked = True
    if parameter_key == "r021":
        for key in all_lock_keys():
            cell = get_or_create_cell(session, workbook, key, column_key)
            cell.locked = key in lock_now
    session.flush()


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
            "workbook_id": workbook.id,
        },
        "created_at": workbook.created_at,
        "updated_at": workbook.updated_at,
        "created_by": workbook.created_by,
        "cells": [cell_to_dict(cell, workbook) for cell in workbook.cells],
        "unsaved_count": len(unsaved),
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
        "extra_parameters": extra_parameters(workbook) if workbook is not None else [],
        "parameter_overrides": parameter_overrides(workbook) if workbook is not None else {},
        "deleted_parameters": sorted(deleted_parameter_keys(workbook)) if workbook is not None else [],
    }
