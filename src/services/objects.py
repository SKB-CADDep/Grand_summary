from __future__ import annotations

import json
import uuid
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.models import ObjectItem, Workbook
from src.paths import objects_seed_path


def _new_id() -> str:
    return str(uuid.uuid4())


def list_objects(session: Session) -> list[ObjectItem]:
    return session.query(ObjectItem).order_by(ObjectItem.name).all()


def get_object(session: Session, object_id: str) -> ObjectItem | None:
    return session.get(ObjectItem, object_id)


def create_object(
    session: Session,
    *,
    name: str,
    station: str | None = None,
    turbine: str | None = None,
    cylinder: str | None = None,
    external_id: str | None = None,
) -> ObjectItem:
    item = ObjectItem(
        id=_new_id(),
        name=name.strip(),
        station=station,
        turbine=turbine,
        cylinder=cylinder,
        external_id=external_id,
    )
    session.add(item)
    session.flush()
    return item


def workbook_for_object(session: Session, object_id: str) -> Workbook | None:
    return (
        session.query(Workbook)
        .filter(Workbook.object_id == object_id)
        .order_by(Workbook.created_at.desc())
        .first()
    )


def seed_objects_if_empty(session: Session) -> int:
    if session.query(ObjectItem).count() > 0:
        return 0
    path = objects_seed_path()
    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for raw in payload:
        create_object(
            session,
            name=raw["name"],
            station=raw.get("station"),
            turbine=raw.get("turbine"),
            cylinder=raw.get("cylinder"),
            external_id=raw.get("external_id"),
        )
        count += 1
    return count


def sync_objects_from_seed(session: Session) -> int:
    """Заглушка будущей синхронизации по external_id (программа Паши / Task Tracker)."""
    path = objects_seed_path()
    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    existing = {item.external_id: item for item in list_objects(session) if item.external_id}
    added = 0
    for raw in payload:
        ext = raw.get("external_id")
        if ext and ext in existing:
            item = existing[ext]
            item.name = raw["name"]
            item.station = raw.get("station")
            item.turbine = raw.get("turbine")
            item.cylinder = raw.get("cylinder")
            continue
        create_object(
            session,
            name=raw["name"],
            station=raw.get("station"),
            turbine=raw.get("turbine"),
            cylinder=raw.get("cylinder"),
            external_id=ext,
        )
        added += 1
    session.flush()
    return added


def import_objects_from_excel(session: Session, path: Path) -> int:
    wb = load_workbook(path, data_only=True)
    sheet = wb.active
    headers = {}
    first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
    for index, value in enumerate(first_row):
        if value is None:
            continue
        headers[str(value).strip().casefold()] = index

    def col(*names: str) -> int | None:
        for name in names:
            if name in headers:
                return headers[name]
        return None

    name_i = col("name", "имя", "наименование", "объект")
    if name_i is None:
        raise ValueError("В Excel нет колонки с именем объекта (name / наименование / объект)")

    station_i = col("station", "станция", "электростанция")
    turbine_i = col("turbine", "турбина")
    cylinder_i = col("cylinder", "цилиндр", "цилиндр пч")
    ext_i = col("external_id", "id", "код")

    count = 0
    for row in sheet.iter_rows(min_row=2, values_only=True):
        name = row[name_i]
        if not name:
            continue
        create_object(
            session,
            name=str(name).strip(),
            station=str(row[station_i]).strip() if station_i is not None and row[station_i] else None,
            turbine=str(row[turbine_i]).strip() if turbine_i is not None and row[turbine_i] else None,
            cylinder=str(row[cylinder_i]).strip() if cylinder_i is not None and row[cylinder_i] else None,
            external_id=str(row[ext_i]).strip() if ext_i is not None and row[ext_i] else None,
        )
        count += 1
    return count
