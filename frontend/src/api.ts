import type {
  Catalog,
  Cell,
  CellChange,
  ChangelogRelease,
  JournalItem,
  NotificationItem,
  ObjectItem,
  ParameterWrite,
  PreviewTable,
  ReportFields,
  TriangleSheetData,
  UnsavedCell,
  VersionItem,
  Workbook,
  WorkbookSheet,
} from './types'

export type HistoryPreferences = {
  history_position: 'right' | 'bottom'
  history_panel_open: boolean
  history_right_width: number
  history_bottom_height: number
}

export type HistoryPreferencesResponse = HistoryPreferences & { configured: boolean }

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function parseError(response: Response): Promise<{ message: string; detail: unknown }> {
  try {
    const data = await response.json()
    if (typeof data.detail === 'string') return { message: data.detail, detail: data.detail }
    return { message: JSON.stringify(data.detail), detail: data.detail }
  } catch {
    return { message: response.statusText, detail: null }
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const parsed = await parseError(response)
    throw new ApiError(parsed.message, response.status, parsed.detail)
  }
  return response.json() as Promise<T>
}

type CellWrite = {
  value?: string | null
  comment?: string
  hyperlink?: string | null
  expected_updated_at?: string | null
}

export const api = {
  me: () =>
    request<{ username: string; can_write: boolean; can_read: boolean; guide_seen: boolean }>('/api/me'),
  markGuideSeen: () =>
    request<{ username: string; can_write: boolean; can_read: boolean; guide_seen: boolean }>(
      '/api/me/guide-seen',
      { method: 'POST' },
    ),
  historyPreferences: () => request<HistoryPreferencesResponse>('/api/me/preferences'),
  saveHistoryPreferences: (preferences: HistoryPreferences, keepalive = false) =>
    request<HistoryPreferencesResponse>('/api/me/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preferences),
      keepalive,
    }),
  objects: () => request<ObjectItem[]>('/api/objects'),
  createObject: (body: {
    factory_number: string
    turbine_name: string
    station_name: string
    station_number: string
    series_turbines: string
    kind: string
  }) =>
    request<ObjectItem>('/api/objects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  openWorkbook: (objectId: string) =>
    request<Workbook>('/api/workbooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ object_id: objectId }),
    }),
  workbook: (id: string) => request<Workbook>(`/api/workbooks/${id}`),
  sheets: (workbookId: string) => request<WorkbookSheet[]>(`/api/workbooks/${workbookId}/sheets`),
  workbookRevision: (workbookId: string) =>
    request<{ revision: string }>(`/api/workbooks/${workbookId}/revision`),
  saveProject: (workbookId: string) =>
    request<{ saved_at: string; sheet_count: number; cell_count: number; draft_count: number }>(
      `/api/workbooks/${workbookId}/save`,
      { method: 'POST' },
    ),
  copySheet: (workbookId: string, name: string) =>
    request<Workbook>(`/api/workbooks/${workbookId}/sheets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  renameSheet: (workbookId: string, sheetId: string, name: string) =>
    request<Workbook>(`/api/workbooks/${workbookId}/sheets/${sheetId}/name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  setPrimarySheet: (workbookId: string, sheetId: string) =>
    request<{ sheets: WorkbookSheet[]; active_sheet_id: string }>(
      `/api/workbooks/${workbookId}/sheets/${sheetId}/primary`,
      { method: 'PATCH' },
    ),
  unsetPrimarySheet: (workbookId: string, sheetId: string) =>
    request<{ sheets: WorkbookSheet[]; active_sheet_id: string }>(
      `/api/workbooks/${workbookId}/sheets/${sheetId}/ordinary`,
      { method: 'PATCH' },
    ),
  deleteSheet: (workbookId: string, sheetId: string) =>
    request<{ sheets: WorkbookSheet[]; active_sheet_id: string }>(
      `/api/workbooks/${workbookId}/sheets/${sheetId}`,
      { method: 'DELETE' },
    ),
  importWorkbook: (workbookId: string, file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<{
      sheets: WorkbookSheet[]
      active_sheet_id: string
      imported: number
    }>(`/api/workbooks/${workbookId}/import-excel`, { method: 'POST', body: data })
  },
  catalog: (workbookId: string) => request<Catalog>(`/api/workbooks/${workbookId}/catalog`),
  addStage: (workbookId: string, label: string) =>
    request<Catalog['columns'][number]>(`/api/workbooks/${workbookId}/stages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
    }),
  updateColumn: (workbookId: string, key: string, label: string) =>
    request<Catalog['columns'][number]>(`/api/workbooks/${workbookId}/columns/${key}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
    }),
  deleteColumn: (workbookId: string, key: string) =>
    request<{ ok: boolean }>(`/api/workbooks/${workbookId}/columns/${key}`, {
      method: 'DELETE',
    }),
  addParameter: (workbookId: string, body: { label: string } & ParameterWrite) =>
    request<Catalog['parameters'][number]>(`/api/workbooks/${workbookId}/parameters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateParameter: (workbookId: string, key: string, body: ParameterWrite) =>
    request<Catalog['parameters'][number]>(`/api/workbooks/${workbookId}/parameters/${key}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteParameter: (workbookId: string, key: string) =>
    request<{ ok: boolean }>(`/api/workbooks/${workbookId}/parameters/${key}`, {
      method: 'DELETE',
    }),
  patchCell: (workbookId: string, parameterKey: string, columnKey: string, body: CellWrite) =>
    request<Cell>(`/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  confirmCell: (workbookId: string, parameterKey: string, columnKey: string, body: CellWrite) =>
    request<Cell>(`/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  addCellComment: (
    workbookId: string,
    parameterKey: string,
    columnKey: string,
    body: { comment: string; expected_updated_at?: string | null },
  ) =>
    request<Cell>(`/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/comment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  setCellUnification: (
    workbookId: string,
    parameterKey: string,
    columnKey: string,
    body: { unified: boolean; expected_updated_at?: string | null },
  ) =>
    request<Cell>(`/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/unification`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  discardCell: (workbookId: string, parameterKey: string, columnKey: string) =>
    request<Cell>(`/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/discard`, {
      method: 'POST',
    }),
  history: (workbookId: string, parameterKey: string, columnKey: string) =>
    request<CellChange[]>(
      `/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/history`,
    ),
  lastCellComment: (workbookId: string, parameterKey: string, columnKey: string) =>
    request<{ comment: string | null }>(
      `/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/last-comment`,
    ).then((result) => result.comment),
  unsaved: (workbookId: string) => request<UnsavedCell[]>(`/api/workbooks/${workbookId}/unsaved`),
  triangles: (workbookId: string) =>
    request<TriangleSheetData[]>(`/api/workbooks/${workbookId}/triangles`),
  importTriangle: (workbookId: string, file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<{ sheets: TriangleSheetData[] }>(`/api/workbooks/${workbookId}/import-triangle`, {
      method: 'POST',
      body: data,
    })
  },
  syncTriangles: (
    workbookId: string,
    body: {
      mode: 'selected' | 'all'
      cells: Array<{ sheet_key: 'geometry' | 'flow_path'; row: number; column: number }>
      target_parameter_key?: string | null
    },
  ) =>
    request<{ updated: number; cleared: number; skipped: number; unsupported_fields: string[]; conflicts: number }>(
      `/api/workbooks/${workbookId}/sync-triangles`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ),
  versions: (workbookId: string) => request<VersionItem[]>(`/api/workbooks/${workbookId}/versions`),
  createVersion: (workbookId: string, kind: string, description: string) =>
    request<VersionItem>(`/api/workbooks/${workbookId}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, description }),
    }),
  restoreVersion: (workbookId: string, versionId: string) =>
    request<Workbook>(`/api/workbooks/${workbookId}/versions/${versionId}/restore`, {
      method: 'POST',
    }),
  exportExcel: async (workbookId: string, scope: 'current' | 'all') => {
    const response = await fetch(`/api/workbooks/${workbookId}/export-excel?scope=${scope}`)
    if (!response.ok) {
      const parsed = await parseError(response)
      throw new ApiError(parsed.message, response.status, parsed.detail)
    }
    return response.blob()
  },
  exportReportTableDocx: async (
    workbookId: string,
    selectedParameterKeys: string[],
    selectedColumnKeys: string[],
    tableNumber = 1,
  ) => {
    const response = await fetch(`/api/workbooks/${workbookId}/export-report-table`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_parameter_keys: selectedParameterKeys,
        selected_column_keys: selectedColumnKeys,
        table_number: tableNumber,
      }),
    })
    if (!response.ok) {
      const parsed = await parseError(response)
      throw new ApiError(parsed.message, response.status, parsed.detail)
    }
    return response.blob()
  },
  reportPreview: (workbookId: string, type: string) => {
    const params = new URLSearchParams({ report_type: type })
    return request<{ type: string; object: string; tables: PreviewTable[] }>(
      `/api/workbooks/${workbookId}/report-preview?${params}`,
    )
  },
  createReport: async (
    workbookId: string,
    type: string,
    fields: ReportFields,
    selectedParameterKeys: string[],
  ) => {
    const response = await fetch(`/api/workbooks/${workbookId}/reports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, ...fields, selected_parameter_keys: selectedParameterKeys }),
    })
    if (!response.ok) {
      const parsed = await parseError(response)
      throw new ApiError(parsed.message, response.status, parsed.detail)
    }
    return response.blob()
  },
  updateStatus: () =>
    request<{
      supported: boolean
      enabled: boolean
      current_version: string
      latest_version: string | null
      update_available: boolean
      message: string | null
    }>('/api/updates'),
  applyUpdate: () =>
    request<{ started: boolean; version: string }>('/api/updates/apply', { method: 'POST' }),
  notifications: () => request<NotificationItem[]>('/api/notifications'),
  readNotification: (id: string) =>
    request<NotificationItem>(`/api/notifications/${id}/read`, { method: 'POST' }),
  changelog: () =>
    request<{ text: string; app_version: string; releases: ChangelogRelease[] }>('/api/changelog'),
  journal: (workbookId?: string | null) => {
    const params = workbookId ? `?workbook_id=${encodeURIComponent(workbookId)}` : ''
    return request<JournalItem[]>(`/api/journal${params}`)
  },
  instruction: () => request<{ text: string }>('/api/instruction'),
  restoreSession: (
    workbookId: string,
    body: {
      cells: Array<{
        parameter_key: string
        column_key: string
        value: string | null
        draft_value: string | null
        status: string
        hyperlink: string | null
        locked: boolean
      }>
      extra_columns?: unknown[]
      column_overrides?: Record<string, string>
      deleted_columns?: string[]
      extra_parameters?: unknown[]
      parameter_overrides?: Record<string, unknown>
      deleted_parameters?: string[]
      remove_change_ids?: string[]
      clear_keys?: Array<{ parameter_key: string; column_key: string }>
      add_changes?: Array<{
        id?: string
        parameter_key: string
        column_key: string
        author: string
        old_value: string | null
        new_value: string | null
        comment: string
      }>
    },
  ) =>
    request<Workbook>(`/api/workbooks/${workbookId}/session-restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}
