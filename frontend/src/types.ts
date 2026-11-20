export type ObjectItem = {
  id: string
  name: string
  station: string | null
  turbine: string | null
  cylinder: string | null
  external_id: string | null
  status: string
  has_workbook: boolean
  workbook_id: string | null
}

export type CatalogColumn = {
  key: string
  label: string
  kind: string
  order: number
}

export type CatalogParameter = {
  key: string
  excel_row: number
  label: string
  group: string
  indent: number
  row_kind: 'section' | 'editable' | 'computed'
  unit: string | null
  order: number
  options?: string[]
}

export type Catalog = {
  columns: CatalogColumn[]
  parameters: CatalogParameter[]
  extra_columns?: CatalogColumn[]
  column_overrides?: Record<string, string>
  deleted_columns?: string[]
  extra_parameters?: Record<string, unknown>[]
  parameter_overrides?: Record<string, unknown>
  deleted_parameters?: string[]
}

export type Cell = {
  parameter_key: string
  column_key: string
  value: string | null
  draft_value: string | null
  status: string
  hyperlink: string | null
  display: string | null
  locked?: boolean
  unified?: boolean
  updated_at?: string | null
  updated_by?: string | null
  options?: string[]
  last_change_id?: string | null
}

export type WorkbookSheet = {
  id: string
  name: string
  order: number
  is_primary: boolean
}

export type Workbook = {
  id: string
  object_id: string
  object: ObjectItem
  created_at: string
  updated_at: string
  created_by: string
  parent_workbook_id: string | null
  sheet_name: string
  sheet_order: number
  is_primary: boolean
  cells: Cell[]
  unsaved_count: number
  imported?: number
}

export type TriangleSheetData = {
  key: 'geometry' | 'flow_path'
  name: string
  rows: string[][]
  merged_ranges: Array<[number, number, number, number]>
  parameter_mapping?: Record<string, string>
  coordinate_mapping?: Record<string, string[]>
}

export type TriangleSourceCell = {
  sheet_key: TriangleSheetData['key']
  row: number
  column: number
}

export type TriangleSyncResult = {
  updated: number
  cleared: number
  skipped: number
  unsupported_fields: string[]
  conflicts: number
}

export type CellChange = {
  id: string
  author: string
  created_at: string
  old_value: string | null
  new_value: string | null
  comment: string
}

export type UnsavedCell = {
  parameter_key: string
  column_key: string
  parameter_label: string
  column_label: string
  draft_value: string | null
  value: string | null
}

export type VersionItem = {
  id: string
  kind: string
  description: string
  created_at: string
  created_by: string
}

export type PreviewCell = {
  column_key: string
  value: string
  changed: boolean
  fill: string | null
}

export type PreviewTable = {
  title: string
  columns: CatalogColumn[]
  rows: { parameter_key: string; label: string; cells: PreviewCell[] }[]
}

export type ReportFields = {
  memo_number: string
  incoming_reference: string
  document_id: string
  narrative: string
  subject: string
  recipient_block: string
}

export type NotificationItem = {
  id: string
  recipient: string
  author: string
  workbook_id: string
  parameter_key: string
  column_key: string
  message: string
  created_at: string
  read: boolean
}

export type ChangelogRelease = {
  version: string
  date: string
  title: string
  items: string[]
}

export type JournalItem = {
  id: string
  created_at: string
  actor: string
  action: string
  action_label: string
  workbook_id: string | null
  object_id: string | null
  object_name: string
  parameter_key: string | null
  column_key: string | null
  old_value: string | null
  new_value: string | null
  comment: string
  summary: string
}

export type ParameterWrite = {
  label?: string
  unit?: string | null
  indent?: number
  group?: string
  row_kind?: 'section' | 'editable'
  insert_after?: string
}

export type TabId = 'object' | 'triangles' | 'table' | 'report'
