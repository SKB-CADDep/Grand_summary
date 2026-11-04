from fastapi import APIRouter, Depends
from backend.schemas import HealthResponse
from backend.dependencies import AppState, get_state

router = APIRouter(
    prefix = "/health",
    tags = ["Health"]
)

@router.get("", response_model=HealthResponse)
def get_health(state: AppState = Depends(get_state)):
    workspace = None
    if state.repository and state.repository.work_dir:
        workspace = state.repository.work_dir
    return HealthResponse(status="ok", workspace=workspace)