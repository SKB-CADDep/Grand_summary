from fastapi import APIRouter, Depends, HTTPException
from backend.dependencies import AppState, get_state, get_repository, open_workspace
from backend.schemas import WorkspaceResponse, WorkspaceOpenRequest, MaterialSummary, MaterialSaveResponse
from pathlib import Path

router = APIRouter(tags=["Materials"])

@router.post("/workspace/open", response_model=WorkspaceResponse)
def workspace_open(body: WorkspaceOpenRequest, state: AppState=Depends(get_state)):
    path = Path(body.directory)
    if not path.exists():
        raise HTTPException(status_code= 400, detail = "Путь не существует")
    if not path.is_dir():
        raise HTTPException(status_code= 400, detail = "Указан не каталог")
    try:
        repo = open_workspace(state, path)
    except Exception as e:
        raise HTTPException(status_code= 500, detail=str(e))

    return WorkspaceResponse(count = len(repo.materials), directory=str(path), application_areas= repo.application_areas)

@router.get("/workspace", response_model=WorkspaceResponse)
def real_workspace(state: AppState=Depends(get_state)):
    if state.repository is None or not state.repository.work_dir:
        raise HTTPException(status_code=404, detail="Workspace не открыт")
    else:
        return WorkspaceResponse(count = len(state.repository.materials), directory=str(state.repository.work_dir), application_areas= state.repository.application_areas)
    
@router.get("/materials")
def get_material(repo= Depends(get_repository)):
    return repo.list_summary()

@router.get("/materials/{material_id}")
def get_material_by_id(material_id:str, repo= Depends(get_repository)):
    material = repo.get_by_id(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Материал не найден")
    else:
        return material.data

@router.put("/materials/{material_id}", response_model=MaterialSaveResponse)
def put_material_by_id(material_id:str, body:dict, repo= Depends(get_repository)):
    if body.get("material_id") != material_id:
        raise HTTPException(status_code=400, detail="id в URL и теле не совпадают")
    if not body.get("metadata"):
        raise HTTPException(status_code=400, detail="Данные материала отсутствуют")
    material = repo.get_by_id(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Материал не найден")
    material.data = body
    repo.save_material(material)
    return MaterialSaveResponse(ok=True, filename=material.filename)
