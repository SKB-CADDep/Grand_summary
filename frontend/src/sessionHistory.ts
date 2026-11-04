import type { Catalog, Cell, Workbook } from './types'

export type CellSnap = {
  parameter_key: string
  column_key: string
  value: string | null
  draft_value: string | null
  status: string
  hyperlink: string | null
  locked: boolean
}

export type ChangeSnap = {
  id: string
  parameter_key: string
  column_key: string
  author: string
  old_value: string | null
  new_value: string | null
  comment: string
}

export type TableSnap = {
  cells: CellSnap[]
  extra_parameters: unknown[]
  parameter_overrides: Record<string, unknown>
  deleted_parameters: string[]
  changeIds: string[]
  changes: ChangeSnap[]
}

export type HistoryEntry = {
  id: number
  label: string
  kind: 'draft' | 'confirm' | 'discard' | 'structure'
  parameterKey?: string
  columnKey?: string
  before: TableSnap
  after: TableSnap
}

export function cellKey(parameterKey: string, columnKey: string) {
  return `${parameterKey}:${columnKey}`
}

export function snapCells(cells: Cell[]): CellSnap[] {
  return cells.map((cell) => ({
    parameter_key: cell.parameter_key,
    column_key: cell.column_key,
    value: cell.value,
    draft_value: cell.draft_value,
    status: cell.status,
    hyperlink: cell.hyperlink,
    locked: Boolean(cell.locked),
  }))
}

export function takeSnap(workbook: Workbook | null, catalog: Catalog | null, extra?: Partial<TableSnap>): TableSnap {
  return {
    cells: snapCells(workbook?.cells || []),
    extra_parameters: catalog?.extra_parameters || [],
    parameter_overrides: catalog?.parameter_overrides || {},
    deleted_parameters: catalog?.deleted_parameters || [],
    changeIds: extra?.changeIds || [],
    changes: extra?.changes || [],
  }
}

export function clearKeys(from: CellSnap[], to: CellSnap[]): CellSnap[] {
  const keep = new Set(to.map((item) => cellKey(item.parameter_key, item.column_key)))
  return from.filter((item) => !keep.has(cellKey(item.parameter_key, item.column_key)))
}

let nextId = 1

export function makeEntry(
  label: string,
  kind: HistoryEntry['kind'],
  before: TableSnap,
  after: TableSnap,
  keys?: { parameterKey?: string; columnKey?: string },
): HistoryEntry {
  nextId += 1
  return {
    id: nextId,
    label,
    kind,
    parameterKey: keys?.parameterKey,
    columnKey: keys?.columnKey,
    before,
    after,
  }
}

export function pushEntry(stack: HistoryEntry[], entry: HistoryEntry): HistoryEntry[] {
  const last = stack[stack.length - 1]
  if (
    last &&
    entry.kind === 'draft' &&
    last.kind === 'draft' &&
    last.parameterKey === entry.parameterKey &&
    last.columnKey === entry.columnKey
  ) {
    return [...stack.slice(0, -1), { ...last, after: entry.after }]
  }
  return [...stack, entry]
}
