from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.dependencies import get_db, require_editor, require_reader
from backend.models import Version
from backend.schemas import (
    AddParameterRequest,
    UpdateParameterRequest,
    AddStageRequest,
    CatalogResponse,
    CellChangeOut,
    CellConfirmRequest,
    CellDraftRequest,
    CellOut,
    ReportCreateRequest,
    SessionRestoreRequest,
    UnsavedCellOut,
    VersionCreate,
    VersionOut,
    WorkbookCreate,
    WorkbookOut,
)
from src.services.workbooks import CellConflict
from src.paths import data_dir
from src.services import objects as object_service
from src.services import reports as report_service
from src.services import triangle_import
from src.services import workbooks as workbook_service

router = APIRouter(tags=["Workbooks"])


def _workbook_or_404(session: Session, workbook_id: str):
    workbook = workbook_service.get_workbook(session, workbook_id)
    if workbook is None:
        raise HTTPException(status_code=404, detail="Сводка не найдена")
    return workbook


@router.get("/catalog", response_model=CatalogResponse)
def get_catalog():
    return workbook_service.catalog_payload()


@router.post("/workbooks", response_model=WorkbookOut)
def create_workbook(
    body: WorkbookCreate,
    session: Session = Depends(get_db),
    username: str = Depends(require_reader),
):
    item = object_service.get_object(session, body.object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Объект не найден")
    workbook, _created = workbook_service.ensure_workbook(session, item, username)
    return workbook_service.workbook_payload(session, workbook)


@router.get("/workbooks/{workbook_id}", response_model=WorkbookOut)
def get_workbook(
    workbook_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.workbook_payload(session, workbook)


@router.get("/workbooks/{workbook_id}/catalog", response_model=CatalogResponse)
def workbook_catalog(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.catalog_payload(workbook)


@router.post("/workbooks/{workbook_id}/stages")
def add_stage(
    workbook_id: str,
    body: AddStageRequest,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="Укажите обозначение ступени")
    return workbook_service.add_stage_column(session, workbook, body.label)


@router.post("/workbooks/{workbook_id}/parameters")
def add_parameter(
    workbook_id: str,
    body: AddParameterRequest,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="Укажите наименование параметра")
    return workbook_service.add_parameter_row(
        session,
        workbook,
        body.label,
        body.group,
        body.unit,
        indent=body.indent,
        row_kind=body.row_kind,
        insert_after=body.insert_after,
        username=_username,
    )


@router.patch("/workbooks/{workbook_id}/parameters/{parameter_key}")
def update_parameter(
    workbook_id: str,
    parameter_key: str,
    body: UpdateParameterRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        return workbook_service.update_parameter_row(
            session,
            workbook,
            parameter_key,
            username,
            label=body.label,
            unit=body.unit,
            indent=body.indent,
            group=body.group,
            row_kind=body.row_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/workbooks/{workbook_id}/parameters/{parameter_key}")
def delete_parameter(
    workbook_id: str,
    parameter_key: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        workbook_service.delete_parameter_row(session, workbook, parameter_key, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.patch("/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}", response_model=CellOut)
def patch_cell(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    body: CellDraftRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        cell = workbook_service.set_draft(
            session,
            workbook,
            parameter_key,
            column_key,
            body.value,
            username,
            hyperlink=body.hyperlink,
            expected_updated_at=body.expected_updated_at,
        )
    except CellConflict as exc:
        raise HTTPException(status_code=409, detail=exc.payload) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workbook_service.cell_to_dict(cell, workbook)


@router.post("/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/confirm", response_model=CellOut)
def confirm_cell(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    body: CellConfirmRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        cell = workbook_service.confirm_cell(
            session,
            workbook,
            parameter_key,
            column_key,
            username,
            body.comment,
            value=body.value,
            hyperlink=body.hyperlink,
            expected_updated_at=body.expected_updated_at,
        )
    except CellConflict as exc:
        raise HTTPException(status_code=409, detail=exc.payload) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workbook_service.cell_to_dict(cell, workbook)


@router.post("/workbooks/{workbook_id}/session-restore", response_model=WorkbookOut)
def session_restore(
    workbook_id: str,
    body: SessionRestoreRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    workbook_service.restore_session(
        session,
        workbook,
        username,
        cells=[item.model_dump() for item in body.cells],
        extra_parameters=body.extra_parameters,
        parameter_overrides=body.parameter_overrides,
        deleted_parameters=body.deleted_parameters,
        remove_change_ids=body.remove_change_ids,
        clear_keys=[item.model_dump() for item in body.clear_keys],
        add_changes=[item.model_dump() for item in body.add_changes],
    )
    session.refresh(workbook)
    return workbook_service.workbook_payload(session, workbook)


@router.post("/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/discard", response_model=CellOut)
def discard_cell(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    cell = workbook_service.discard_draft(session, workbook, parameter_key, column_key)
    return workbook_service.cell_to_dict(cell, workbook)


@router.get(
    "/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/history",
    response_model=list[CellChangeOut],
)
def cell_history(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.cell_history(session, workbook, parameter_key, column_key)


@router.get("/workbooks/{workbook_id}/unsaved", response_model=list[UnsavedCellOut])
def unsaved(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.unsaved_cells(session, workbook)


@router.post("/workbooks/{workbook_id}/import-triangle")
def import_triangle(
    workbook_id: str,
    file: UploadFile,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    filename = file.filename or "triangle.xlsx"
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx (треугольники)")
    target = data_dir() / "_upload_triangle.xlsx"
    target.write_bytes(file.file.read())
    try:
        values = triangle_import.parse_triangle_excel(target)
        count = workbook_service.apply_imported_values(session, workbook, values, username, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать файл: {exc}") from exc
    finally:
        target.unlink(missing_ok=True)
    payload = workbook_service.workbook_payload(session, workbook)
    payload["imported"] = count
    return payload


@router.get("/workbooks/{workbook_id}/versions", response_model=list[VersionOut])
def list_versions(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    versions = sorted(workbook.versions, key=lambda item: item.created_at, reverse=True)
    return versions


@router.post("/workbooks/{workbook_id}/versions", response_model=VersionOut)
def create_version(
    workbook_id: str,
    body: VersionCreate,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.create_version(session, workbook, username, body.kind, body.description)


@router.post("/workbooks/{workbook_id}/versions/{version_id}/restore", response_model=WorkbookOut)
def restore_version(
    workbook_id: str,
    version_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    version = session.get(Version, version_id)
    if version is None or version.workbook_id != workbook.id:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    workbook_service.restore_version(session, workbook, version)
    return workbook_service.workbook_payload(session, workbook)


@router.get("/workbooks/{workbook_id}/report-preview")
def report_preview(
    workbook_id: str,
    report_type: str = "short",
    compare_version_id: str | None = None,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    compare = None
    if compare_version_id:
        compare = session.get(Version, compare_version_id)
        if compare is None or compare.workbook_id != workbook.id:
            raise HTTPException(status_code=404, detail="Версия для сравнения не найдена")
    kind = report_type if report_type in {"short", "full"} else "short"
    return {
        "type": kind,
        "object": workbook.object.name,
        "tables": report_service.preview_tables(workbook, kind, compare),
    }


@router.post("/workbooks/{workbook_id}/reports")
def create_report(
    workbook_id: str,
    body: ReportCreateRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    compare = None
    if body.compare_version_id:
        compare = session.get(Version, body.compare_version_id)
        if compare is None or compare.workbook_id != workbook.id:
            raise HTTPException(status_code=404, detail="Версия для сравнения не найдена")
    report_type = body.type if body.type in {"short", "full"} else "short"
    content = report_service.build_report_docx(session, workbook, report_type, compare, body.extra_notes)
    workbook_service.create_version(
        session,
        workbook,
        username,
        kind="report_snapshot",
        description=f"Сводка ({report_type})",
    )
    filename = f"grand_summary_{report_type}.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
