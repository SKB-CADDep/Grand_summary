from __future__ import annotations
from pydantic import BaseModel
from typing import Literal

class WorkspaceOpenRequest(BaseModel):
    directory: str

class WorkspaceResponse(BaseModel):
    count: int
    directory: str
    application_areas: list[str]

class OkResponse(BaseModel):
    ok: bool

class MaterialSummary(BaseModel):
    id: str
    name: str
    areas: list[str]
    filename: str

class MaterialSaveResponse(BaseModel):
    ok: bool
    filename: str

class HardnessConvertRequest(BaseModel):
    value: float
    from_unit: str
    to_unit: str

class HardnessConvertResponse(BaseModel):
    result: float | None
    from_unit: str
    to_unit: str

class HardnessColumnsResponse(BaseModel):
    columns: list[str]
    system_unit: str

class HealthResponse(BaseModel):
    status: str
    workspace: str | None

class SourceCreateRequest(BaseModel):
    group: Literal["property_sources", "strength_sources", "chemical_sources"]
    name: str
    description: str = ""
    hyperlink: str = ""

class SourceUpdateRequest(BaseModel):
    name: str
    description: str = ""
    hyperlink: str = ""

class SourcesResponse(BaseModel):
    property_sources: list[dict[str,str]]
    strength_sources: list[dict[str,str]]
    chemical_sources: list[dict[str,str]]

class SourceItem(BaseModel):
    id_source: str
    name_source: str
    description: str
    hyperlink: str

class PropertiesResponse(BaseModel):
    physical: dict[str, dict]
    mechanical: dict[str, dict]