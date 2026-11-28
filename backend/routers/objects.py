from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.dependencies import get_db, require_editor, require_reader
from backend.schemas import ObjectCreate, ObjectOut, WorkbookOut
from src.services import objects as object_service
from src.services import workbooks as workbook_service

router = APIRouter(tags=["Objects"])


def _to_out(session: Session, item) -> ObjectOut:
    workbook = object_service.workbook_for_object(session, item.id)
    sheet_count = 0
    if workbook is not None:
        sheet_count = 1 + len(list(workbook.sheets))
    return ObjectOut(
        id=item.id,
        name=item.name,
        station=item.station,
        turbine=item.turbine,
        cylinder=item.cylinder,
        external_id=item.external_id,
        status=item.status,
        has_workbook=workbook is not None,
        workbook_id=workbook.id if workbook else None,
        workbook_updated_at=workbook.updated_at if workbook else None,
        last_edited_by=object_service.last_editor_for_workbook(session, workbook) if workbook else None,
        started_by=workbook.created_by if workbook else None,
        sheet_count=sheet_count,
    )


def _catalog_error(exc: object) -> HTTPException:
    return HTTPException(status_code=503, detail=f"Общий каталог объектов недоступен: {exc}")


@router.get("/objects", response_model=list[ObjectOut])
def list_objects(session: Session = Depends(get_db), _username: str = Depends(require_reader)):
    try:
        items = object_service.list_objects(session)
    except object_service.ObjectCatalogError as exc:
        raise _catalog_error(exc) from exc
    return [_to_out(session, item) for item in items]


@router.post("/objects", response_model=ObjectOut, status_code=201)
def create_object(
    body: ObjectCreate,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    try:
        item = object_service.create_object(
            session,
            factory_number=body.factory_number,
            turbine_name=body.turbine_name,
            station_name=body.station_name,
            station_number=body.station_number,
            series_turbines=body.series_turbines,
            kind=body.kind,
            updated_by=username,
        )
    except object_service.ObjectCatalogError as exc:
        raise _catalog_error(exc) from exc
    except OSError as exc:
        raise _catalog_error(exc) from exc
    return _to_out(session, item)


@router.post("/objects/{object_id}/workbook", response_model=WorkbookOut)
def open_object_workbook(
    object_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_reader),
):
    item = object_service.get_object(session, object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Объект не найден")
    workbook, _created = workbook_service.ensure_workbook(session, item, username)
    return workbook_service.workbook_payload(session, workbook)
