from __future__ import annotations

from datetime import datetime
from typing import Literal

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


class HistoryPreferencesIn(BaseModel):
    history_position: Literal["right", "bottom"] = "right"
    history_panel_open: bool = True
    history_right_width: int = Field(default=360, ge=100, le=760)
    history_bottom_height: int = Field(default=260, ge=140, le=600)


class HistoryPreferencesOut(HistoryPreferencesIn):
    configured: bool = True


class ObjectCreate(BaseModel):
    factory_number: str
    turbine_name: str
    station_name: str
    station_number: str
    series_turbines: str
    kind: str


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
    workbook_updated_at: datetime | None = None
    last_edited_by: str | None = None
    started_by: str | None = None
    sheet_count: int = 0


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
    unified: bool = False
    excel_highlight: bool = False
    updated_at: str | None = None
    updated_by: str | None = None
    options: list[str] = []
    last_change_id: str | None = None
    compare_highlight: bool = False
    compare_against: list["CellCompareSheetOut"] = Field(default_factory=list)


class CellUnificationRequest(BaseModel):
    unified: bool
    expected_updated_at: str | None = None


class CellDraftRequest(BaseModel):
    value: str | None = None
    hyperlink: str | None = None
    expected_updated_at: str | None = None


class CellConfirmRequest(BaseModel):
    value: str | None = None
    comment: str = Field(min_length=1)
    hyperlink: str | None = None
    expected_updated_at: str | None = None


class CellCommentRequest(BaseModel):
    comment: str = Field(min_length=1)
    expected_updated_at: str | None = None


class CellChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    author: str
    created_at: datetime
    old_value: str | None
    new_value: str | None
    comment: str


class CellCompareRequest(BaseModel):
    sheet_ids: list[str] = Field(default_factory=list)
    range_from: str | None = None
    range_to: str | None = None
    combine: Literal["and", "or"] = "or"


class CellCompareSheetOut(BaseModel):
    sheet_id: str
    sheet_name: str
    value: str | None = None
    differs: bool = False


class CellCompareOut(BaseModel):
    parameter_key: str
    column_key: str
    combine: Literal["and", "or"]
    current: CellCompareSheetOut
    targets: list[CellCompareSheetOut]
    differs_any: bool
    differs_all: bool


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
    excel_highlight: bool = False


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
    extra_columns: list[dict] | None = None
    column_overrides: dict | None = None
    deleted_columns: list[str] | None = None
    extra_parameters: list[dict] | None = None
    parameter_overrides: dict | None = None
    deleted_parameters: list[str] | None = None
    remove_change_ids: list[str] = []
    clear_keys: list[CellSnap] = []
    add_changes: list[ChangeSnap] = []


class CatalogResponse(BaseModel):
    columns: list[dict]
    parameters: list[dict]
    column_overrides: dict = {}
    deleted_columns: list[str] = []
    extra_columns: list[dict] = []
    extra_parameters: list[dict] = []
    parameter_overrides: dict = {}
    deleted_parameters: list[str] = []


class ReportNoteOut(BaseModel):
    id: str
    parameter_key: str
    column_key: str
    text: str
    created_at: str
    author: str = ""
    number: int


class WorkbookOut(BaseModel):
    id: str
    object_id: str
    object: ObjectOut
    created_at: datetime
    updated_at: datetime
    created_by: str
    parent_workbook_id: str | None = None
    sheet_name: str = "Основная таблица"
    sheet_order: int = 0
    is_primary: bool = False
    is_issued: bool = False
    issued_kind: str = ""
    is_base: bool = False
    show_change_highlight: bool = True
    cells: list[CellOut]
    unsaved_count: int = 0
    report_notes: list[ReportNoteOut] = Field(default_factory=list)


class SheetCompareOut(BaseModel):
    combine: Literal["and", "or"]
    workbook: WorkbookOut
    catalog: CatalogResponse
    targets: list[CellCompareSheetOut]
    changed_count: int = 0


class SheetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SheetRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SheetIssuedRequest(BaseModel):
    issued: bool
    issued_kind: str | None = None


class IssueVersionRequest(BaseModel):
    issued_kind: str = "preliminary"


class SheetChangeHighlightRequest(BaseModel):
    enabled: bool


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
    selected_parameter_keys: list[str] = Field(default_factory=list)
    memo_number: str = ""
    incoming_reference: str = ""
    document_id: str = ""
    recipient_block: str = ""
    subject: str = ""
    greeting: str = ""
    narrative: str = ""
    signature_block: str = ""
    extra_notes: str = ""


class ReportTableExportRequest(BaseModel):
    selected_parameter_keys: list[str] = Field(default_factory=list)
    selected_column_keys: list[str] = Field(default_factory=list)
    table_number: int = Field(default=1, ge=1)


class ReportNoteCreateRequest(BaseModel):
    parameter_key: str
    column_key: str
    text: str = Field(min_length=1)


class ChangelogResponse(BaseModel):
    text: str
    app_version: str
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


class NotificationObjectSetting(BaseModel):
    object_id: str
    object_name: str = ""
    enabled: bool = True
    watch_my_cells: bool = True
    watch_all_cells: bool = False


class NotificationSettingsOut(BaseModel):
    watch_my_cells: bool = True
    objects: list[NotificationObjectSetting] = Field(default_factory=list)


class NotificationSettingsIn(BaseModel):
    watch_my_cells: bool = True
    objects: list[NotificationObjectSetting] = Field(default_factory=list)


class TriangleSourceCell(BaseModel):
    sheet_key: str = Field(min_length=1, max_length=32)
    row: int = Field(ge=11)
    column: int = Field(ge=2)


class TriangleSyncRequest(BaseModel):
    mode: Literal["selected", "all"]
    cells: list[TriangleSourceCell] = Field(default_factory=list)
    target_parameter_key: str | None = None
