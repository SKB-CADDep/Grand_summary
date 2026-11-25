from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.models import ObjectItem, Workbook
from src.paths import objects_database_path


class ObjectCatalogError(ValueError):
    pass


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _record_name(record: dict[str, Any]) -> str:
    return (
        f"{_text(record.get('station_name'))} (ст.{_text(record.get('station_number'))}) "
        f"{_text(record.get('turbine_name'))} (зав.{_text(record.get('factory_number'))})"
    )


def read_object_catalog() -> list[dict[str, Any]]:
    path = objects_database_path()
    if not path.is_file():
        raise ObjectCatalogError(f"Файл общего каталога объектов не найден: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectCatalogError(f"Не удалось прочитать общий каталог объектов: {exc}") from exc
    if not isinstance(payload, list):
        raise ObjectCatalogError("Файл каталога объектов должен содержать JSON-массив.")
    for record in payload:
        if not isinstance(record, dict) or record.get("ID_projects") is None:
            raise ObjectCatalogError("В каталоге найдена запись без ID_projects.")
    return payload


def _local_object(session: Session, record: dict[str, Any]) -> ObjectItem:
    external_id = _text(record.get("ID_projects"))
    item = session.query(ObjectItem).filter(ObjectItem.external_id == external_id).first()
    if item is None:
        item = ObjectItem(id=str(uuid.uuid4()), external_id=external_id, name=_record_name(record))
        session.add(item)
    item.name = _record_name(record)
    item.station = _text(record.get("station_name")) or None
    item.turbine = _text(record.get("turbine_name")) or None
    item.cylinder = None
    item.status = "active"
    return item


def list_objects(session: Session) -> list[ObjectItem]:
    catalog = read_object_catalog()
    items = [_local_object(session, record) for record in catalog]
    session.flush()
    return sorted(items, key=lambda item: item.name.casefold())


def get_object(session: Session, object_id: str) -> ObjectItem | None:
    return session.get(ObjectItem, object_id)


def _next_project_id(records: list[dict[str, Any]], session: Session) -> str:
    ids = {_text(record.get("ID_projects")) for record in records}
    for item in session.query(ObjectItem.external_id).all():
        if item[0]:
            ids.add(_text(item[0]))
    numeric_ids = [int(value) for value in ids if value.isdecimal()]
    candidate = max(numeric_ids, default=0) + 1
    while str(candidate) in ids:
        candidate += 1
    return str(candidate)


def create_object(
    session: Session,
    *,
    factory_number: str,
    turbine_name: str,
    station_name: str,
    station_number: str,
    series_turbines: str,
    kind: str,
    updated_by: str,
) -> ObjectItem:
    records = read_object_catalog()
    project_id = _next_project_id(records, session)
    record = {
        "ID_projects": project_id,
        "factory_number": factory_number.strip(),
        "turbine_name": turbine_name.strip(),
        "station_name": station_name.strip(),
        "station_number": station_number.strip(),
        "series_turbines": series_turbines.strip(),
        "kind": kind.strip(),
        "hidden": False,
        "object_version": 1,
        "updated_by": updated_by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return _local_object(session, record)


def workbook_for_object(session: Session, object_id: str) -> Workbook | None:
    return (
        session.query(Workbook)
        .filter(Workbook.object_id == object_id, Workbook.parent_workbook_id.is_(None))
        .order_by(Workbook.created_at.desc())
        .first()
    )
