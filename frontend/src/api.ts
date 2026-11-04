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
  UnsavedCell,
  VersionItem,
  Workbook,
} from './types'

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
  objects: () => request<ObjectItem[]>('/api/objects'),
  syncObjects: () => request<ObjectItem[]>('/api/objects/sync'),
  createObject: (body: Partial<ObjectItem> & { name: string }) =>
    request<ObjectItem>('/api/objects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  importObjects: (file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<ObjectItem[]>('/api/objects/import-excel', { method: 'POST', body: data })
  },
  openWorkbook: (objectId: string) =>
    request<Workbook>('/api/workbooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ object_id: objectId }),
    }),
  workbook: (id: string) => request<Workbook>(`/api/workbooks/${id}`),
  catalog: (workbookId: string) => request<Catalog>(`/api/workbooks/${workbookId}/catalog`),
  addStage: (workbookId: string, label: string) =>
    request<Catalog['columns'][number]>(`/api/workbooks/${workbookId}/stages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
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
  discardCell: (workbookId: string, parameterKey: string, columnKey: string) =>
    request<Cell>(`/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/discard`, {
      method: 'POST',
    }),
  history: (workbookId: string, parameterKey: string, columnKey: string) =>
    request<CellChange[]>(
      `/api/workbooks/${workbookId}/cells/${parameterKey}/${columnKey}/history`,
    ),
  unsaved: (workbookId: string) => request<UnsavedCell[]>(`/api/workbooks/${workbookId}/unsaved`),
  importTriangle: (workbookId: string, file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<Workbook>(`/api/workbooks/${workbookId}/import-triangle`, {
      method: 'POST',
      body: data,
    })
  },
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
  reportPreview: (workbookId: string, type: string, compareVersionId: string | null) => {
    const params = new URLSearchParams({ report_type: type })
    if (compareVersionId) params.set('compare_version_id', compareVersionId)
    return request<{ type: string; object: string; tables: PreviewTable[] }>(
      `/api/workbooks/${workbookId}/report-preview?${params}`,
    )
  },
  createReport: async (
    workbookId: string,
    type: string,
    compareVersionId: string | null,
    extraNotes: string,
  ) => {
    const response = await fetch(`/api/workbooks/${workbookId}/reports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type,
        compare_version_id: compareVersionId,
        extra_notes: extraNotes,
      }),
    })
    if (!response.ok) {
      const parsed = await parseError(response)
      throw new ApiError(parsed.message, response.status, parsed.detail)
    }
    return response.blob()
  },
  notifications: () => request<NotificationItem[]>('/api/notifications'),
  readNotification: (id: string) =>
    request<NotificationItem>(`/api/notifications/${id}/read`, { method: 'POST' }),
  changelog: () => request<{ text: string; releases: ChangelogRelease[] }>('/api/changelog'),
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
