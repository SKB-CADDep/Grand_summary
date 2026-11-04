from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.models import AuditEvent, Cell, CellChange, ObjectItem, Workbook
from src.paths import docs_dir

ACTION_LABELS = {
    "confirmed": "Изменено",
    "parameter_added": "Параметр добавлен",
    "parameter_changed": "Параметр изменён",
    "parameter_deleted": "Параметр удалён",
    "imported": "Импорт",
    "version": "Версия",
    "report": "Сводка",
}

HEADER_RE = re.compile(
    r"^v(?P<version>\S+)\s+(?P<date>\d{4}\.\d{2}\.\d{2})\s+—\s+(?P<title>.+?):\s*$"
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    workbook: Workbook | None = None,
    parameter_key: str | None = None,
    column_key: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    comment: str = "",
    summary: str = "",
) -> AuditEvent:
    event = AuditEvent(
        id=_new_id(),
        created_at=_now(),
        actor=actor,
        action=action,
        workbook_id=workbook.id if workbook else None,
        object_id=workbook.object_id if workbook else None,
        parameter_key=parameter_key,
        column_key=column_key,
        old_value=old_value,
        new_value=new_value,
        comment=comment or "",
        summary=summary or "",
    )
    session.add(event)
    session.flush()
    return event


def parse_changelog(text: str | None = None) -> list[dict]:
    raw = text
    if raw is None:
        path = docs_dir() / "changelog.md"
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
    releases: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        header = HEADER_RE.match(line.strip())
        if header:
            current = {
                "version": header.group("version"),
                "date": header.group("date"),
                "title": header.group("title").strip(),
                "items": [],
            }
            releases.append(current)
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            current["items"].append(stripped[2:].strip())
    return releases


def _object_name(obj: ObjectItem | None) -> str:
    return obj.name if obj else ""


def list_user_journal(session: Session, workbook_id: str | None = None) -> list[dict]:
    rows: list[dict] = []
    changes = session.query(CellChange).all()
    for change in changes:
        cell: Cell | None = change.cell
        if cell is None:
            continue
        workbook = cell.workbook
        if workbook_id and workbook and workbook.id != workbook_id:
            continue
        obj = workbook.object if workbook else None
        rows.append(
            {
                "id": f"cell:{change.id}",
                "created_at": change.created_at,
                "actor": change.author,
                "action": "confirmed",
                "action_label": ACTION_LABELS["confirmed"],
                "workbook_id": workbook.id if workbook else None,
                "object_id": workbook.object_id if workbook else None,
                "object_name": _object_name(obj),
                "parameter_key": cell.parameter_key,
                "column_key": cell.column_key,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "comment": change.comment,
                "summary": f"{cell.parameter_key}/{cell.column_key}: {change.old_value or '—'} → {change.new_value or '—'}",
            }
        )
    query = session.query(AuditEvent)
    if workbook_id:
        query = query.filter(AuditEvent.workbook_id == workbook_id)
    for event in query.all():
        obj = session.get(ObjectItem, event.object_id) if event.object_id else None
        rows.append(
            {
                "id": event.id,
                "created_at": event.created_at,
                "actor": event.actor,
                "action": event.action,
                "action_label": ACTION_LABELS.get(event.action, event.action),
                "workbook_id": event.workbook_id,
                "object_id": event.object_id,
                "object_name": _object_name(obj),
                "parameter_key": event.parameter_key,
                "column_key": event.column_key,
                "old_value": event.old_value,
                "new_value": event.new_value,
                "comment": event.comment,
                "summary": event.summary or event.comment,
            }
        )
    def _sort_key(item: dict) -> datetime:
        value = item.get("created_at") or _now()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    rows.sort(key=_sort_key, reverse=True)
    return rows
