from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.dependencies import get_db, get_username, require_reader
from backend.schemas import (
    ChangelogResponse,
    HealthResponse,
    InstructionResponse,
    JournalItemOut,
    NotificationOut,
    UserResponse,
)
from src.paths import docs_dir
from src.services import acl
from src.services import guide as guide_service
from src.services import journal as journal_service
from src.services import workbooks as workbook_service

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def health(username: str = Depends(get_username)):
    return HealthResponse(status="ok", user=username, can_write=acl.can_write(username))


@router.get("/me", response_model=UserResponse)
def me(username: str = Depends(get_username)):
    return UserResponse(
        username=username,
        can_write=acl.can_write(username),
        can_read=acl.can_read(username),
        guide_seen=guide_service.is_guide_seen(username),
    )


@router.post("/me/guide-seen", response_model=UserResponse)
def mark_guide_seen(username: str = Depends(get_username)):
    guide_service.mark_guide_seen(username)
    return UserResponse(
        username=username,
        can_write=acl.can_write(username),
        can_read=acl.can_read(username),
        guide_seen=True,
    )


@router.get("/changelog", response_model=ChangelogResponse)
def changelog():
    path = docs_dir() / "changelog.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else "Журнал изменений пока пуст."
    return ChangelogResponse(text=text, releases=journal_service.parse_changelog(text))


@router.get("/journal", response_model=list[JournalItemOut])
def user_journal(
    workbook_id: str | None = None,
    session: Session = Depends(get_db),
    _username: str = Depends(require_reader),
):
    return journal_service.list_user_journal(session, workbook_id)


@router.get("/instruction", response_model=InstructionResponse)
def instruction():
    path = docs_dir() / "instruction.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else "Инструкция не найдена."
    return InstructionResponse(text=text)


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(session: Session = Depends(get_db), username: str = Depends(require_reader)):
    return workbook_service.list_notifications(session, username)


@router.post("/notifications/{note_id}/read", response_model=NotificationOut)
def read_notification(
    note_id: str,
    session: Session = Depends(get_db),
    username: str = Depends(require_reader),
):
    note = workbook_service.mark_notification_read(session, note_id, username)
    if note is None:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return note
