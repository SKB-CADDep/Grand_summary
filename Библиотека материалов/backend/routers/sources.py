from fastapi import APIRouter, Depends, HTTPException
from backend.dependencies import AppState, get_state
from backend.schemas import SourcesResponse, SourceItem, SourceCreateRequest, OkResponse, SourceUpdateRequest

router = APIRouter(tags=["Sources"])

@router.get("/sources", response_model=SourcesResponse)
def get_sources(state: AppState = Depends(get_state)):
    return SourcesResponse(property_sources=state.sources.sources["property_sources"], strength_sources=state.sources.sources["strength_sources"], chemical_sources=state.sources.sources["chemical_sources"])

@router.get("/sources/{source_id}", response_model=SourceItem)
def get_source_by_id(source_id:str, state: AppState=Depends(get_state)):
    res = state.sources.get_source_by_id(source_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Ресурс не найден")
    return SourceItem(id_source=res["id_source"], name_source=res["name_source"], description=res["description"], hyperlink=res["hyperlink"])

@router.post("/sources", status_code=201)
def post_source(body:SourceCreateRequest, state: AppState=Depends(get_state)):
    id_source = state.sources.add_source(name=body.name, description=body.description, hyperlink=body.hyperlink, group=body.group)
    return state.sources.get_source_by_id(id_source)

@router.put("/sources/{source_id}")
def put_source(source_id:str, body: SourceUpdateRequest, state: AppState=Depends(get_state)):
    res = state.sources.update_source(source_id=source_id, name=body.name, description=body.description, hyperlink=body.hyperlink)
    if not res:
        raise HTTPException(status_code=404, detail="Не удалось обновить источник")
    else:
        return state.sources.get_source_by_id(source_id)


@router.delete("/sources/{source_id}", response_model=OkResponse)
def delete_by_id(source_id:str, state: AppState=Depends(get_state)):
    if state.sources.get_source_by_id(source_id) is None:
        raise HTTPException(status_code=404, detail="Ресурс не найден")
    else:
        state.sources.delete_source(source_id)
        return OkResponse(ok=True)
    