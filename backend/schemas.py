from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    user: str
    app: str = "grand_summary"
    can_write: bool = True


class UserResponse(BaseModel):
    username: str
    can_write: bool = True
    can_read: bool = True
    guide_seen: bool = False


class ObjectCreate(BaseModel):
    name: str
    station: str | None = None
    turbine: str | None = None
    cylinder: str | None = None
    external_id: str | None = None


class ObjectOut(BaseModel):
    id: str
    name: str
    station: str | None
    turbine: str | None
    cylinder: str | None
    external_id: str | None
    status: str
    has_workbook: bool = False
    workbook_id: str | None = None


class WorkbookCreate(BaseModel):
    object_id: str


class CellOut(BaseModel):
    parameter_key: str
    column_key: str
    value: str | None
    draft_value: str | None
    status: str
    hyperlink: str | None
    display: str | None = None
    locked: bool = False
    updated_at: str | None = None
    updated_by: str | None = None
    options: list[str] = []
    last_change_id: str | None = None


class CellDraftRequest(BaseModel):
    value: str | None = None
    hyperlink: str | None = None
    expected_updated_at: str | None = None


class CellConfirmRequest(BaseModel):
    value: str | None = None
    comment: str = Field(min_length=1)
    hyperlink: str | None = None
    expected_updated_at: str | None = None


class CellChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    author: str
    created_at: datetime
    old_value: str | None
    new_value: str | None
    comment: str


class UnsavedCellOut(BaseModel):
    parameter_key: str
    column_key: str
    parameter_label: str
    column_label: str
    draft_value: str | None
    value: str | None


class VersionCreate(BaseModel):
    kind: str = "issued"
    description: str = ""


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    description: str
    created_at: datetime
    created_by: str


class CellSnap(BaseModel):
    parameter_key: str
    column_key: str
    value: str | None = None
    draft_value: str | None = None
    status: str = "empty"
    hyperlink: str | None = None
    locked: bool = False


class ChangeSnap(BaseModel):
    id: str | None = None
    parameter_key: str
    column_key: str
    author: str = ""
    old_value: str | None = None
    new_value: str | None = None
    comment: str = ""


class SessionRestoreRequest(BaseModel):
    cells: list[CellSnap] = []
    extra_parameters: list[dict] | None = None
    parameter_overrides: dict | None = None
    deleted_parameters: list[str] | None = None
    remove_change_ids: list[str] = []
    clear_keys: list[CellSnap] = []
    add_changes: list[ChangeSnap] = []


class CatalogResponse(BaseModel):
    columns: list[dict]
    parameters: list[dict]
    extra_parameters: list[dict] = []
    parameter_overrides: dict = {}
    deleted_parameters: list[str] = []


class WorkbookOut(BaseModel):
    id: str
    object_id: str
    object: ObjectOut
    created_at: datetime
    updated_at: datetime
    created_by: str
    cells: list[CellOut]
    unsaved_count: int = 0


class AddStageRequest(BaseModel):
    label: str


class AddParameterRequest(BaseModel):
    label: str
    group: str = ""
    unit: str | None = None
    indent: int | None = None
    row_kind: str = "editable"
    insert_after: str | None = None


class UpdateParameterRequest(BaseModel):
    label: str | None = None
    unit: str | None = None
    indent: int | None = None
    group: str | None = None
    row_kind: str | None = None


class ReportCreateRequest(BaseModel):
    type: str = "short"
    compare_version_id: str | None = None
    extra_notes: str = ""


class ChangelogResponse(BaseModel):
    text: str
    releases: list[dict] = []


class JournalItemOut(BaseModel):
    id: str
    created_at: datetime
    actor: str
    action: str
    action_label: str
    workbook_id: str | None = None
    object_id: str | None = None
    object_name: str = ""
    parameter_key: str | None = None
    column_key: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    comment: str = ""
    summary: str = ""


class InstructionResponse(BaseModel):
    text: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    recipient: str
    author: str
    workbook_id: str
    parameter_key: str
    column_key: str
    message: str
    created_at: datetime
    read: bool
