from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.models import Cell, NotificationSetting, Workbook
from src.services import objects as object_service

GLOBAL_OBJECT_ID = ""

DEFAULTS = {
    "enabled": True,
    "watch_my_cells": True,
    "watch_all_cells": False,
}


def _new_id() -> str:
    return str(uuid.uuid4())


def _row_payload(row: NotificationSetting | None, *, object_id: str, object_name: str = "") -> dict:
    source = row
    return {
        "object_id": object_id or None,
        "object_name": object_name,
        "enabled": DEFAULTS["enabled"] if source is None else bool(source.enabled),
        "watch_my_cells": DEFAULTS["watch_my_cells"] if source is None else bool(source.watch_my_cells),
        "watch_all_cells": DEFAULTS["watch_all_cells"] if source is None else bool(source.watch_all_cells),
    }


def _get_row(session: Session, username: str, object_id: str) -> NotificationSetting | None:
    return (
        session.query(NotificationSetting)
        .filter(NotificationSetting.username == username, NotificationSetting.object_id == (object_id or ""))
        .first()
    )


def effective_settings(session: Session, username: str, object_id: str) -> dict:
    global_row = _get_row(session, username, GLOBAL_OBJECT_ID)
    object_row = _get_row(session, username, object_id) if object_id else None
    global_payload = _row_payload(global_row, object_id=GLOBAL_OBJECT_ID)
    if object_row is None:
        return {
            "enabled": True,
            "watch_my_cells": global_payload["watch_my_cells"],
            "watch_all_cells": False,
        }
    return _row_payload(object_row, object_id=object_id)


def list_settings(session: Session, username: str) -> dict:
    global_row = _get_row(session, username, GLOBAL_OBJECT_ID)
    objects = []
    for item in object_service.list_objects(session):
        workbook = object_service.workbook_for_object(session, item.id)
        if workbook is None:
            continue
        row = _get_row(session, username, item.id)
        payload = _row_payload(row, object_id=item.id, object_name=item.name)
        if row is None:
            payload["watch_my_cells"] = _row_payload(global_row, object_id=GLOBAL_OBJECT_ID)["watch_my_cells"]
        objects.append(payload)
    objects.sort(key=lambda item: (item.get("object_name") or "").casefold())
    return {
        "watch_my_cells": _row_payload(global_row, object_id=GLOBAL_OBJECT_ID)["watch_my_cells"],
        "objects": objects,
    }


def _upsert(session: Session, username: str, object_id: str, payload: dict) -> NotificationSetting:
    row = _get_row(session, username, object_id)
    if row is None:
        row = NotificationSetting(
            id=_new_id(),
            username=username,
            object_id=object_id or "",
        )
        session.add(row)
    row.enabled = bool(payload.get("enabled", DEFAULTS["enabled"]))
    row.watch_my_cells = bool(payload.get("watch_my_cells", DEFAULTS["watch_my_cells"]))
    row.watch_all_cells = bool(payload.get("watch_all_cells", DEFAULTS["watch_all_cells"]))
    return row


def save_settings(session: Session, username: str, payload: dict) -> dict:
    _upsert(
        session,
        username,
        GLOBAL_OBJECT_ID,
        {
            "enabled": True,
            "watch_my_cells": payload.get("watch_my_cells", True),
            "watch_all_cells": False,
        },
    )
    known = {item.id for item in object_service.list_objects(session)}
    for item in payload.get("objects") or []:
        object_id = str(item.get("object_id") or "")
        if not object_id or object_id not in known:
            continue
        _upsert(session, username, object_id, item)
    session.flush()
    return list_settings(session, username)


def recipients_for_cell_change(
    session: Session,
    workbook: Workbook,
    cell: Cell,
    author: str,
    previous_author: str | None,
) -> list[str]:
    object_id = workbook.object_id
    recipients: set[str] = set()
    prior_authors = {change.author for change in cell.changes if change.author}
    if previous_author:
        prior_authors.add(previous_author)
    prior_authors.discard(author)
    for username in prior_authors:
        prefs = effective_settings(session, username, object_id)
        if prefs["enabled"] and prefs["watch_my_cells"]:
            recipients.add(username)
    watchers = (
        session.query(NotificationSetting)
        .filter(
            NotificationSetting.object_id == object_id,
            NotificationSetting.enabled.is_(True),
            NotificationSetting.watch_all_cells.is_(True),
        )
        .all()
    )
    for row in watchers:
        if row.username != author:
            recipients.add(row.username)
    return sorted(recipients)
