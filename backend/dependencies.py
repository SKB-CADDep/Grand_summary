from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.database import get_session
from src.identity import current_user
from src.services import acl


def get_db(session: Session = Depends(get_session)) -> Session:
    return session


def get_username(request: Request) -> str:
    return current_user(request)


def require_reader(username: str = Depends(get_username)) -> str:
    if not acl.can_read(username):
        raise HTTPException(status_code=403, detail="Нет доступа к Гранд сводке")
    return username


def require_editor(username: str = Depends(get_username)) -> str:
    if not acl.can_write(username):
        raise HTTPException(status_code=403, detail="Нет прав на изменение (только отдел ОР)")
    return username
