from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services import updates as update_service

router = APIRouter(tags=["Updates"])


@router.get("/updates")
def update_status():
    return update_service.status()


@router.post("/updates/apply")
def apply_update():
    try:
        return update_service.apply_update()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
