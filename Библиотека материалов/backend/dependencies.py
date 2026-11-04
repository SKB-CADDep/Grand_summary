from dataclasses import dataclass
from functools import lru_cache
from fastapi import Depends, HTTPException
from pathlib import Path
from src.infrastructure.storage_backend import LocalDirectoryStorage
from src.services.material_repository import MaterialRepository
from src.services.properties_catalog import PropertiesCatalog
from src.services.hardness_table import HardnessTable
from src.services.source_service import SourceService

@dataclass
class AppState:
    properties: PropertiesCatalog | None = None
    hardness: HardnessTable | None = None
    sources: SourceService | None = None

    storage: LocalDirectoryStorage | None = None
    repository: MaterialRepository | None = None

@lru_cache
def get_app_state() -> AppState:
    """Один экземпляр AppState на процесс uvicorn."""
    return AppState(
        properties = PropertiesCatalog(),
        hardness = HardnessTable(),
        sources = SourceService()
    )

def get_state() -> AppState:
    return get_app_state()

def get_repository(state: AppState = Depends(get_state)) -> MaterialRepository:
    if state.repository is None:
        raise HTTPException(status_code = 409, detail="Workspace не открыт")
    return state.repository

def open_workspace(state: AppState, directory: Path) -> MaterialRepository:
    state.storage = LocalDirectoryStorage(directory)
    state.repository = MaterialRepository(source_service = state.sources, storage=state.storage)
    state.repository.load_materials_from_dir(directory)
    return state.repository