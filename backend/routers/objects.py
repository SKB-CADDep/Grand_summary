from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.dependencies import get_db, require_editor, require_reader
from backend.schemas import ObjectCreate, ObjectOut, WorkbookOut
from src.paths import data_dir
from src.services import objects as object_service
from src.services import workbooks as workbook_service

router = APIRouter(tags=["Objects"])


def _to_out(session: Session, item) -> ObjectOut:
    workbook = object_service.workbook_for_object(session, item.id)
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
    )


@router.get("/objects", response_model=list[ObjectOut])
def list_objects(session: Session = Depends(get_db), _username: str = Depends(require_reader)):
    object_service.seed_objects_if_empty(session)
    return [_to_out(session, item) for item in object_service.list_objects(session)]


@router.get("/objects/sync", response_model=list[ObjectOut])
def sync_objects(session: Session = Depends(get_db), _username: str = Depends(require_editor)):
    object_service.sync_objects_from_seed(session)
    return [_to_out(session, item) for item in object_service.list_objects(session)]


@router.post("/objects", response_model=ObjectOut, status_code=201)
def create_object(
    body: ObjectCreate,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    item = object_service.create_object(
        session,
        name=body.name,
        station=body.station,
        turbine=body.turbine,
        cylinder=body.cylinder,
        external_id=body.external_id,
    )
    return _to_out(session, item)


@router.post("/objects/import-excel", response_model=list[ObjectOut])
def import_objects(
    file: UploadFile,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    suffix = (file.filename or "").lower()
    if not suffix.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx")
    target = data_dir() / "_upload_objects.xlsx"
    target.write_bytes(file.file.read())
    try:
        object_service.import_objects_from_excel(session, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        target.unlink(missing_ok=True)
    return [_to_out(session, item) for item in object_service.list_objects(session)]


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
