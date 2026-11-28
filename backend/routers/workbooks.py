from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.dependencies import get_db, require_editor, require_reader
from backend.models import Cell, TriangleSheet, Version, Workbook
from backend.schemas import (
    AddParameterRequest,
    UpdateParameterRequest,
    AddStageRequest,
    CatalogResponse,
    CellChangeOut,
    CellCompareOut,
    CellCompareRequest,
    CellCommentRequest,
    SheetCompareOut,
    CellConfirmRequest,
    CellDraftRequest,
    CellOut,
    CellUnificationRequest,
    ReportCreateRequest,
    ReportNoteCreateRequest,
    ReportNoteOut,
    ReportTableExportRequest,
    SessionRestoreRequest,
    SheetChangeHighlightRequest,
    SheetCreateRequest,
    IssueVersionRequest,
    SheetIssuedRequest,
    SheetRenameRequest,
    TriangleSyncRequest,
    UnsavedCellOut,
    VersionCreate,
    VersionOut,
    WorkbookCreate,
    WorkbookOut,
)
from src.services.workbooks import CellConflict
from src.services.journal import add_audit
from src.services import objects as object_service
from src.services import reports as report_service
from src.services import triangle_import
from src.services import workbook_export
from src.services import workbook_import
from src.services import workbooks as workbook_service

router = APIRouter(tags=["Workbooks"])


def _workbook_or_404(session: Session, workbook_id: str):
    workbook = workbook_service.get_workbook(session, workbook_id)
    if workbook is None:
        raise HTTPException(status_code=404, detail="Сводка не найдена")
    return workbook


def _require_ordinary_sheet(workbook: Workbook) -> None:
    if workbook.is_base:
        raise HTTPException(status_code=400, detail="Базовый лист доступен только для просмотра")


def _ordinary_workbook_or_400(session: Session, workbook_id: str) -> Workbook:
    workbook = _workbook_or_404(session, workbook_id)
    _require_ordinary_sheet(workbook)
    if workbook.is_issued:
        raise HTTPException(status_code=400, detail="Выданная версия доступна только для просмотра")
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


@router.get("/workbooks/{workbook_id}/sheets")
def list_sheets(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return [
        workbook_service.sheet_brief(item)
        for item in workbook_service.list_sheet_workbooks(session, workbook)
    ]


@router.get("/workbooks/{workbook_id}/revision")
def project_revision(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    sheets = workbook_service.list_sheet_workbooks(session, root)
    sheet_ids = [item.id for item in sheets]
    cell_stats = {
        row[0]: {
            "count": row[1],
            "updated_at": row[2].isoformat() if row[2] else None,
        }
        for row in (
            session.query(
                Cell.workbook_id,
                func.count(Cell.id),
                func.max(Cell.updated_at),
            )
            .filter(Cell.workbook_id.in_(sheet_ids))
            .group_by(Cell.workbook_id)
            .all()
        )
    }
    triangle_updates = {
        row[0]: row[1].isoformat() if row[1] else None
        for row in session.query(TriangleSheet.workbook_id, func.max(TriangleSheet.updated_at))
        .filter(TriangleSheet.workbook_id.in_(sheet_ids))
        .group_by(TriangleSheet.workbook_id)
        .all()
    }
    state = [
        {
            "id": item.id,
            "name": item.sheet_name,
            "order": item.sheet_order,
            "is_primary": item.is_primary,
            "is_issued": bool(item.is_issued),
            "is_base": bool(item.is_base),
            "show_change_highlight": bool(item.show_change_highlight),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "cells": cell_stats.get(item.id, {}),
            "triangles_updated_at": triangle_updates.get(item.id),
            "structure": [
                item.extra_columns_json,
                item.column_overrides_json,
                item.deleted_columns_json,
                item.extra_parameters_json,
                item.parameter_overrides_json,
                item.deleted_parameters_json,
                getattr(item, "report_notes_json", None) or "[]",
            ],
        }
        for item in sheets
    ]
    revision = hashlib.sha256(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"revision": revision}


@router.post("/workbooks/{workbook_id}/save")
def save_project(
    workbook_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    sheets = workbook_service.list_sheet_workbooks(session, root)
    sheet_ids = [item.id for item in sheets]
    session.flush()
    cell_count = session.query(Cell).filter(Cell.workbook_id.in_(sheet_ids)).count()
    draft_count = (
        session.query(Cell)
        .filter(Cell.workbook_id.in_(sheet_ids), Cell.status == "draft")
        .count()
    )
    add_audit(
        session,
        actor=username,
        action="project_saved",
        workbook=root,
        comment="Проект сохранён в текущем состоянии",
        summary=f"Сохранено листов: {len(sheets)}, черновиков: {draft_count}",
    )
    saved_at = datetime.now(timezone.utc).isoformat()
    session.commit()
    try:
        from src.services.db_backup import write_current_snapshot

        write_current_snapshot()
    except Exception:
        pass
    return {
        "saved_at": saved_at,
        "sheet_count": len(sheets),
        "cell_count": cell_count,
        "draft_count": draft_count,
    }


@router.post("/workbooks/{workbook_id}/sheets", response_model=WorkbookOut)
def create_sheet_copy(
    workbook_id: str,
    body: SheetCreateRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Укажите название нового листа")
    clone = workbook_import.copy_sheet(session, workbook, body.name, username)
    return workbook_service.workbook_payload(session, clone)


@router.patch("/workbooks/{workbook_id}/sheets/{sheet_id}/name", response_model=WorkbookOut)
def rename_sheet(
    workbook_id: str,
    sheet_id: str,
    body: SheetRenameRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        renamed = workbook_service.rename_sheet(session, target, body.name, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workbook_service.workbook_payload(session, renamed)


@router.patch("/workbooks/{workbook_id}/sheets/{sheet_id}/primary")
def set_primary_sheet(
    workbook_id: str,
    sheet_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        sheets = workbook_service.set_primary_sheet(session, target, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": target.id,
    }


@router.post("/workbooks/{workbook_id}/issue-version")
def issue_version(
    workbook_id: str,
    body: IssueVersionRequest | None = None,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        sheets, issued = workbook_service.issue_version(
            session, workbook, username, body.issued_kind if body else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": issued.id,
        "issued_sheet_id": issued.id,
    }


@router.patch("/workbooks/{workbook_id}/sheets/{sheet_id}/issued")
def set_sheet_issued(
    workbook_id: str,
    sheet_id: str,
    body: SheetIssuedRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        updated = workbook_service.set_sheet_issued(
            session, target, body.issued, username, body.issued_kind
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sheets = workbook_service.list_sheet_workbooks(session, root)
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": updated.id,
    }


@router.patch("/workbooks/{workbook_id}/sheets/{sheet_id}/base")
def set_base_sheet(
    workbook_id: str,
    sheet_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        sheets = workbook_service.set_base_sheet(session, target, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    base = next((item for item in sheets if item.is_base), target)
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": base.id,
    }


@router.patch("/workbooks/{workbook_id}/sheets/{sheet_id}/change-highlight")
def set_change_highlight(
    workbook_id: str,
    sheet_id: str,
    body: SheetChangeHighlightRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        updated = workbook_service.set_change_highlight(session, target, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sheets = workbook_service.list_sheet_workbooks(session, root)
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": updated.id,
    }


@router.patch("/workbooks/{workbook_id}/sheets/{sheet_id}/ordinary")
def unset_primary_sheet(
    workbook_id: str,
    sheet_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        sheets = workbook_service.unset_primary_sheet(session, target, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": target.id,
    }


@router.delete("/workbooks/{workbook_id}/sheets/{sheet_id}")
def delete_sheet(
    workbook_id: str,
    sheet_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    target = session.get(Workbook, sheet_id)
    if target is None or (target.id != root.id and target.parent_workbook_id != root.id):
        raise HTTPException(status_code=404, detail="Лист не найден")
    try:
        sheets, active_id = workbook_service.delete_sheet_workbook(session, root, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sheets": [workbook_service.sheet_brief(item) for item in sheets],
        "active_sheet_id": active_id,
    }


@router.get("/workbooks/{workbook_id}/export-excel")
def export_excel(
    workbook_id: str,
    scope: str = Query(default="current"),
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    if scope not in {"current", "all"}:
        raise HTTPException(status_code=400, detail="Допустимый режим выгрузки: current или all")
    workbook = _workbook_or_404(session, workbook_id)
    content = workbook_export.build_workbook_export(session, workbook, scope)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="grand_summary_{scope}.xlsx"'},
    )


@router.post("/workbooks/{workbook_id}/export-report-table")
def export_report_table(
    workbook_id: str,
    body: ReportTableExportRequest,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    if not body.selected_parameter_keys or not body.selected_column_keys:
        raise HTTPException(status_code=400, detail="Выберите строки и столбцы для экспорта")
    workbook = _workbook_or_404(session, workbook_id)
    try:
        content = report_service.build_id_table_docx(
            workbook,
            body.selected_parameter_keys,
            body.selected_column_keys,
            body.table_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="id_table_{body.table_number}.docx"'},
    )


@router.post("/workbooks/{workbook_id}/report-notes", response_model=list[ReportNoteOut])
def add_report_note(
    workbook_id: str,
    body: ReportNoteCreateRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        return workbook_service.add_report_note(
            session, workbook, body.parameter_key, body.column_key, body.text, username
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/workbooks/{workbook_id}/report-notes/{note_id}", response_model=list[ReportNoteOut])
def delete_report_note(
    workbook_id: str,
    note_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    try:
        return workbook_service.delete_report_note(session, workbook, note_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workbooks/{workbook_id}/import-excel")
async def import_excel_sheets(
    workbook_id: str,
    file: UploadFile,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Поддерживаются только файлы .xlsx")
    root = _workbook_or_404(session, workbook_id)
    root = root.parent or root
    try:
        imported_excel = workbook_import.load_excel_workbook(BytesIO(await file.read()))
        importable_sheets = [
            sheet
            for sheet in imported_excel.worksheets
            if workbook_import.is_importable_sheet_title(sheet.title)
        ]
        if not importable_sheets:
            raise ValueError("В Excel-файле нет листов для импорта")
        sheets = workbook_service.list_sheet_workbooks(session, root)
        if workbook_service.is_placeholder_main_name(root.sheet_name) and not workbook_import.workbook_has_values(root):
            root.sheet_name = workbook_service.MAIN_SHEET_NAME
        structure_source = root
        created: list[Workbook] = []
        imported_count = 0
        grids: list[dict] = []
        parameters_present: list[set[str]] = []
        columns_present: list[set[str]] = []
        existing_names = {item.sheet_name.casefold() for item in sheets}
        for index, excel_sheet in enumerate(importable_sheets):
            base_name = excel_sheet.title[:255] or f"Лист {index + 1}"
            name = base_name
            suffix = 2
            while name.casefold() in existing_names:
                ending = f" ({suffix})"
                name = f"{base_name[:255 - len(ending)]}{ending}"
                suffix += 1
            existing_names.add(name.casefold())
            target = workbook_import.copy_sheet(
                session, structure_source, name, username, include_values=False
            )
            target.sheet_name = name
            count, grid, present_parameters, present_columns = workbook_import.import_sheet(
                session, target, excel_sheet, username
            )
            imported_count += count
            grids.append(grid)
            parameters_present.append(present_parameters)
            columns_present.append(present_columns)
            created.append(target)
            structure_source = target
        journaled = workbook_import.record_excel_journal(
            session, created, grids, parameters_present, columns_present, username
        )
        imported_excel.close()
        session.flush()
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "sheets": [
            workbook_service.sheet_brief(item)
            for item in workbook_service.list_sheet_workbooks(session, root)
        ],
        "active_sheet_id": root.id,
        "imported": imported_count,
        "journaled": journaled,
    }


@router.post("/workbooks/{workbook_id}/clear-excel-highlight")
def clear_excel_highlight(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    cleared = workbook_service.clear_excel_highlight(session, workbook)
    session.commit()
    return {"cleared": cleared}


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
    username: str = Depends(require_editor),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="Укажите обозначение ступени")
    return workbook_service.add_stage_column(session, workbook, body.label, username)


@router.patch("/workbooks/{workbook_id}/columns/{column_key}")
def update_column(
    workbook_id: str,
    column_key: str,
    body: AddStageRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    try:
        return workbook_service.update_column_label(session, workbook, column_key, body.label, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/workbooks/{workbook_id}/columns/{column_key}")
def remove_column(
    workbook_id: str,
    column_key: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    try:
        workbook_service.delete_column(session, workbook, column_key, username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/workbooks/{workbook_id}/parameters")
def add_parameter(
    workbook_id: str,
    body: AddParameterRequest,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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


@router.post(
    "/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/comment",
    response_model=CellOut,
)
def add_cell_comment(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    body: CellCommentRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    try:
        cell = workbook_service.add_cell_comment(
            session,
            workbook,
            parameter_key,
            column_key,
            username,
            body.comment,
            expected_updated_at=body.expected_updated_at,
        )
    except CellConflict as exc:
        raise HTTPException(status_code=409, detail=exc.payload) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workbook_service.cell_to_dict(cell, workbook)


@router.patch(
    "/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/unification",
    response_model=CellOut,
)
def set_cell_unification(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    body: CellUnificationRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_reader),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    try:
        cell = workbook_service.set_cell_unification(
            session,
            workbook,
            parameter_key,
            column_key,
            username,
            body.unified,
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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    workbook_service.restore_session(
        session,
        workbook,
        username,
        cells=[item.model_dump() for item in body.cells],
        extra_parameters=body.extra_parameters,
        parameter_overrides=body.parameter_overrides,
        deleted_parameters=body.deleted_parameters,
        extra_columns=body.extra_columns,
        column_overrides=body.column_overrides,
        deleted_columns=body.deleted_columns,
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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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


@router.post(
    "/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/compare",
    response_model=CellCompareOut,
)
def compare_cell(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    body: CellCompareRequest,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.compare_cell_across_sheets(
        session,
        workbook,
        parameter_key,
        column_key,
        sheet_ids=body.sheet_ids,
        range_from=body.range_from,
        range_to=body.range_to,
        combine=body.combine,
    )


@router.post("/workbooks/{workbook_id}/compare-sheet", response_model=SheetCompareOut)
def compare_sheet(
    workbook_id: str,
    body: CellCompareRequest,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.compare_sheet_across_sheets(
        session,
        workbook,
        sheet_ids=body.sheet_ids,
        range_from=body.range_from,
        range_to=body.range_to,
        combine=body.combine,
    )


@router.get("/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/last-comment")
def cell_last_comment(
    workbook_id: str,
    parameter_key: str,
    column_key: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
) -> dict[str, str | None]:
    workbook = _workbook_or_404(session, workbook_id)
    return {
        "comment": workbook_service.latest_cell_comment(
            session, workbook, parameter_key, column_key
        )
    }


@router.get("/workbooks/{workbook_id}/unsaved", response_model=list[UnsavedCellOut])
def unsaved(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    return workbook_service.unsaved_cells(session, workbook)


@router.get("/workbooks/{workbook_id}/triangles")
def get_triangle_sheets(
    workbook_id: str,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    root = workbook.parent or workbook
    sheets = session.query(TriangleSheet).filter(TriangleSheet.workbook_id == root.id).all()
    parsed = []
    for sheet in sheets:
        data = json.loads(sheet.data_json)
        data.setdefault("key", sheet.sheet_key)
        data.setdefault("name", sheet.sheet_name)
        data.setdefault("parameter_mapping", triangle_import.triangle_parameter_mapping(sheet.sheet_key))
        data.setdefault("coordinate_mapping", triangle_import.triangle_coordinate_mapping(sheet.sheet_key))
        parsed.append(data)
    parsed.sort(key=triangle_import.triangle_sheet_sort_key)
    return parsed


@router.post("/workbooks/{workbook_id}/sync-triangles")
def sync_triangles(
    workbook_id: str,
    body: TriangleSyncRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _ordinary_workbook_or_400(session, workbook_id)
    if body.mode == "selected" and not body.cells:
        raise HTTPException(status_code=400, detail="Сначала выделите ячейки треугольника")
    try:
        result = triangle_import.sync_triangle_data(
            session,
            workbook,
            username,
            body.mode,
            [item.model_dump() for item in body.cells],
            body.target_parameter_key,
        )
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        status_code = 409 if "черновик" in str(exc).casefold() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise


@router.post("/workbooks/{workbook_id}/import-triangle")
async def import_triangle(
    workbook_id: str,
    file: UploadFile,
    session: Session = Depends(get_db),
    _username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    filename = file.filename or "triangle.xlsx"
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx (треугольники)")
    try:
        parsed_sheets = triangle_import.parse_triangle_sheets(BytesIO(await file.read()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    root = workbook.parent or workbook
    incoming_keys = {parsed["key"] for parsed in parsed_sheets}
    try:
        (
            session.query(TriangleSheet)
            .filter(
                TriangleSheet.workbook_id == root.id,
                TriangleSheet.sheet_key.notin_(incoming_keys),
            )
            .delete(synchronize_session=False)
        )
        for parsed in parsed_sheets:
            stored = (
                session.query(TriangleSheet)
                .filter(
                    TriangleSheet.workbook_id == root.id,
                    TriangleSheet.sheet_key == parsed["key"],
                )
                .one_or_none()
            )
            if stored is None:
                stored = TriangleSheet(
                    id=str(uuid.uuid4()),
                    workbook_id=root.id,
                    sheet_key=parsed["key"],
                    sheet_name=parsed["name"],
                    data_json="",
                )
                session.add(stored)
            stored.sheet_name = parsed["name"]
            stored.data_json = json.dumps(parsed, ensure_ascii=False)
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"sheets": parsed_sheets}


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
    workbook = _ordinary_workbook_or_400(session, workbook_id)
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
    selected_parameter_keys: list[str] = Query(default=[]),
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    workbook = _workbook_or_404(session, workbook_id)
    kind = report_type if report_type in {"short", "full"} else "short"
    compare = None
    if compare_version_id:
        compare = session.get(Version, compare_version_id)
        if compare is None or compare.workbook_id != workbook.id:
            raise HTTPException(status_code=404, detail="Версия для сравнения не найдена")
    else:
        compare = (
            session.query(Version)
            .filter(
                Version.workbook_id == workbook.id,
                Version.kind == "report_snapshot",
                Version.description == f"Служебная записка ({kind})",
            )
            .order_by(Version.created_at.desc())
            .first()
        )
    return {
        "type": kind,
        "object": workbook.object.name,
        "tables": report_service.preview_tables(workbook, kind, compare, selected_parameter_keys),
    }


@router.post("/workbooks/{workbook_id}/reports")
def create_report(
    workbook_id: str,
    body: ReportCreateRequest,
    session: Session = Depends(get_db),
    username: str = Depends(require_editor),
):
    workbook = _workbook_or_404(session, workbook_id)
    report_type = body.type if body.type in {"short", "full"} else "short"
    compare = None
    if body.compare_version_id:
        compare = session.get(Version, body.compare_version_id)
        if compare is None or compare.workbook_id != workbook.id:
            raise HTTPException(status_code=404, detail="Версия для сравнения не найдена")
    else:
        compare = (
            session.query(Version)
            .filter(
                Version.workbook_id == workbook.id,
                Version.kind == "report_snapshot",
                Version.description == f"Служебная записка ({report_type})",
            )
            .order_by(Version.created_at.desc())
            .first()
        )
    content = report_service.build_report_docx(
        session,
        workbook,
        report_type,
        compare,
        body.extra_notes,
        body.selected_parameter_keys,
        body.model_dump(),
    )
    report_snapshot = report_service.report_snapshot_cells(
        workbook,
        compare,
        body.selected_parameter_keys,
    )
    workbook_service.create_version(
        session,
        workbook,
        username,
        kind="report_snapshot",
        description=f"Служебная записка ({report_type})",
        snapshot=report_snapshot,
    )
    filename = f"service_memo_{report_type}.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
