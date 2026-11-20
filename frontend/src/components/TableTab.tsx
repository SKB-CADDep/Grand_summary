import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import type {
  Catalog,
  Cell,
  CellChange,
  ParameterWrite,
  UnsavedCell,
  Workbook,
  WorkbookSheet,
} from '../types'
import { CellDictSelect } from './CellDictSelect'

type Selection = { parameterKey: string; columnKey: string }
type TableSearchResult = { id: string }
type HistoryPosition = 'right' | 'bottom'
type ContextMenuState = {
  x: number
  y: number
  selection: Selection | null
  sheetId?: string
  area?: 'history'
}

type Props = {
  objectName: string
  catalog: Catalog | null
  workbook: Workbook | null
  unsaved: UnsavedCell[]
  history: CellChange[]
  sheets: WorkbookSheet[]
  busy: boolean
  canWrite: boolean
  historyPosition: HistoryPosition
  historyPanelOpen: boolean
  historySizes: { right: number; bottom: number }
  onHistorySizeChange: (position: HistoryPosition, size: number) => void
  onShowHistory: () => void
  onHideHistory: () => void
  onSaveAllDrafts: () => void
  onSelectSheet: (sheetId: string) => void
  onCopySheet: (sheetId?: string) => void
  onRenameSheet: (sheetId: string) => void
  onSetPrimarySheet: (sheetId: string) => void
  onUnsetPrimarySheet: (sheetId: string) => void
  onDeleteSheet: (sheetId: string) => void
  onImportWorkbook: (file: File) => void
  onExportCurrent: () => void
  onExportAll: () => void
  onComposeReport: () => void
  onSaveProject: () => Promise<void>
  onDraft: (parameterKey: string, columnKey: string, value: string, hyperlink: string | null) => Promise<boolean>
  onConfirm: (
    parameterKey: string,
    columnKey: string,
    value: string,
    comment: string,
    hyperlink: string | null,
  ) => Promise<boolean>
  onSelectCell: (selection: Selection) => void
  onLoadCellComment: (parameterKey: string, columnKey: string) => Promise<string | null>
  onAddComment: (parameterKey: string, columnKey: string, comment: string) => Promise<boolean>
  onToggleUnification: (
    parameterKey: string,
    columnKey: string,
    unified: boolean,
  ) => Promise<void>
  onAddParameter: (body: { label: string } & ParameterWrite) => void
  onUpdateParameter: (key: string, body: ParameterWrite) => void
  onDeleteParameter: (key: string) => void
  onAddColumn: (label: string) => void
  onUpdateColumn: (key: string, label: string) => void
  onDeleteColumn: (key: string) => void
  onDiscard: (parameterKey: string, columnKey: string) => void
}

const tableDataPropKeys: (keyof Props)[] = [
  'objectName',
  'catalog',
  'workbook',
  'unsaved',
  'history',
  'sheets',
  'busy',
  'canWrite',
  'historyPosition',
  'historyPanelOpen',
  'historySizes',
]

function areTablePropsEqual(previous: Props, next: Props): boolean {
  return tableDataPropKeys.every((key) => previous[key] === next[key])
}

function displayLabel(label: string, unit: string | null | undefined): string {
  const suffix = unit?.trim()
  if (!suffix) return label
  const tail = `, ${suffix}`
  if (label.endsWith(tail)) return label.slice(0, -tail.length).trim()
  return label
}

function highlightSearchText(text: string, query: string, active: boolean): ReactNode {
  const needle = query.trim()
  if (!needle) return text
  const foldedText = text.toLocaleLowerCase()
  const foldedNeedle = needle.toLocaleLowerCase()
  const parts: ReactNode[] = []
  let cursor = 0
  let matchIndex = foldedText.indexOf(foldedNeedle)

  while (matchIndex >= 0) {
    if (matchIndex > cursor) parts.push(text.slice(cursor, matchIndex))
    parts.push(
      <mark key={matchIndex} className={active ? 'table-find-match active' : 'table-find-match'}>
        {text.slice(matchIndex, matchIndex + needle.length)}
      </mark>,
    )
    cursor = matchIndex + needle.length
    matchIndex = foldedText.indexOf(foldedNeedle, cursor)
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts.length ? parts : text
}

function nextCell(
  catalog: Catalog,
  cells: Map<string, Cell>,
  selection: Selection | null,
  key: string,
): Selection | null {
  const rows = catalog.parameters.filter((item) => item.row_kind === 'editable').map((item) => item.key)
  const cols = catalog.columns.map((item) => item.key)
  if (!rows.length || !cols.length) return null
  let row = selection ? rows.indexOf(selection.parameterKey) : 0
  let col = selection ? cols.indexOf(selection.columnKey) : 0
  if (row < 0) row = 0
  if (col < 0) col = 0
  let dr = 0
  let dc = 0
  if (key === 'ArrowUp') dr = -1
  if (key === 'ArrowDown') dr = 1
  if (key === 'ArrowLeft') dc = -1
  if (key === 'ArrowRight' || key === 'Tab') dc = 1
  if (key === 'ShiftTab') dc = -1
  if (key === 'Tab') {
    col += 1
    if (col >= cols.length) {
      col = 0
      row += 1
    }
  } else if (key === 'ShiftTab') {
    col -= 1
    if (col < 0) {
      col = cols.length - 1
      row -= 1
    }
  } else {
    row += dr
    col += dc
  }
  while (row >= 0 && row < rows.length && col >= 0 && col < cols.length) {
    const cell = cells.get(`${rows[row]}:${cols[col]}`)
    if (!cell?.locked && !cell?.unified) return { parameterKey: rows[row], columnKey: cols[col] }
    if (key === 'Tab') {
      col += 1
      if (col >= cols.length) {
        col = 0
        row += 1
      }
    } else if (key === 'ShiftTab') {
      col -= 1
      if (col < 0) {
        col = cols.length - 1
        row -= 1
      }
    } else {
      row += dr
      col += dc
    }
  }
  return selection
}

function cellMap(workbook: Workbook | null): Map<string, Cell> {
  const map = new Map<string, Cell>()
  if (!workbook) return map
  for (const cell of workbook.cells) {
    map.set(`${cell.parameter_key}:${cell.column_key}`, cell)
  }
  return map
}

function TableTabContent({
  objectName,
  catalog,
  workbook,
  unsaved,
  history,
  sheets,
  busy,
  canWrite,
  historyPosition,
  historyPanelOpen,
  historySizes,
  onHistorySizeChange,
  onShowHistory,
  onHideHistory,
  onSaveAllDrafts,
  onSelectSheet,
  onCopySheet,
  onRenameSheet,
  onSetPrimarySheet,
  onUnsetPrimarySheet,
  onDeleteSheet,
  onImportWorkbook,
  onComposeReport,
  onSaveProject,
  onExportCurrent,
  onExportAll,
  onDraft,
  onConfirm,
  onSelectCell,
  onLoadCellComment,
  onAddComment,
  onToggleUnification,
  onAddParameter,
  onUpdateParameter,
  onDeleteParameter,
  onAddColumn,
  onUpdateColumn,
  onDeleteColumn,
  onDiscard,
}: Props) {
  const [selection, setSelection] = useState<Selection | null>(null)
  const [editValue, setEditValue] = useState('')
  const [link, setLink] = useState('')
  const [comment, setComment] = useState('')
  const [cellComment, setCellComment] = useState('')
  const [commentMode, setCommentMode] = useState(false)
  const [draftSaveTarget, setDraftSaveTarget] = useState<Selection | null>(null)
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [tableMode, setTableMode] = useState<'view' | 'edit'>('view')
  const [structureEdit, setStructureEdit] = useState(false)
  const [structKey, setStructKey] = useState('')
  const [structLabel, setStructLabel] = useState('')
  const [structUnit, setStructUnit] = useState('')
  const [structIndent, setStructIndent] = useState(1)
  const [columnKey, setColumnKey] = useState('')
  const [columnLabel, setColumnLabel] = useState('')
  const [newColumnLabel, setNewColumnLabel] = useState('')
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [findIndex, setFindIndex] = useState(0)
  const [resizingHistory, setResizingHistory] = useState(false)
  const historySize = historySizes[historyPosition]
  const gridRef = useRef<HTMLDivElement | null>(null)
  const sheetAreaRef = useRef<HTMLDivElement | null>(null)
  const contextMenuRef = useRef<HTMLDivElement | null>(null)
  const cellCommentTooltipRef = useRef<HTMLDivElement | null>(null)
  const hoverCommentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hoveredCellKeyRef = useRef<string | null>(null)
  const cellCommentCacheRef = useRef(new Map<string, string | null>())
  const commentInputRef = useRef<HTMLTextAreaElement | null>(null)
  const findInputRef = useRef<HTMLInputElement | null>(null)
  const findTargetsRef = useRef(new Map<string, HTMLElement>())
  const findTargetRefsRef = useRef(new Map<string, (node: HTMLElement | null) => void>())
  const suppressCellBlurRef = useRef(false)
  const pendingDraftRef = useRef<{
    selection: Selection
    value: string
    hyperlink: string | null
    promise: Promise<boolean>
  } | null>(null)
  const cells = useMemo(() => cellMap(workbook), [workbook])
  const visibleFindQuery = findOpen ? findQuery : ''
  const findResults = useMemo(() => {
    const needle = findQuery.trim().toLocaleLowerCase()
    if (!findOpen || !needle || !catalog) return []
    const results: TableSearchResult[] = []
    const addIfMatched = (id: string, text: string) => {
      if (text.toLocaleLowerCase().includes(needle)) results.push({ id })
    }

    for (const column of catalog.columns) addIfMatched(`column:${column.key}`, column.label)
    for (const param of catalog.parameters) {
      addIfMatched(`parameter:${param.key}`, displayLabel(param.label, param.unit))
      if (param.unit) addIfMatched(`unit:${param.key}`, param.unit)
      if (param.row_kind !== 'editable') continue
      for (const column of catalog.columns) {
        const cell = cells.get(`${param.key}:${column.key}`)
        const isSelected = selection?.parameterKey === param.key && selection.columnKey === column.key
        const isEditingSelected = isSelected && tableMode === 'edit' && canWrite && !busy && !cell?.locked
        const text = isEditingSelected
          ? editValue
          : cell?.display ?? cell?.draft_value ?? cell?.value ?? ''
        addIfMatched(`cell:${param.key}:${column.key}`, text)
      }
    }
    return results
  }, [catalog, cells, findOpen, findQuery, selection, tableMode, canWrite, busy, editValue])
  const activeFindResult = findResults[findIndex]
  const contextMenuSheet = contextMenu?.sheetId
    ? sheets.find((sheet) => sheet.id === contextMenu.sheetId) ?? null
    : null

  useEffect(() => {
    if (!contextMenu) return
    const dismissOutsideMenu = (event: globalThis.PointerEvent) => {
      if (!contextMenuRef.current?.contains(event.target as Node)) setContextMenu(null)
    }
    const dismissOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setContextMenu(null)
    }
    document.addEventListener('pointerdown', dismissOutsideMenu)
    window.addEventListener('keydown', dismissOnEscape)
    return () => {
      document.removeEventListener('pointerdown', dismissOutsideMenu)
      window.removeEventListener('keydown', dismissOnEscape)
    }
  }, [contextMenu])

  useEffect(() => {
    cellCommentCacheRef.current.clear()
    hoveredCellKeyRef.current = null
    if (hoverCommentTimerRef.current) window.clearTimeout(hoverCommentTimerRef.current)
  }, [workbook?.id, workbook?.updated_at])

  useEffect(() => () => {
    if (hoverCommentTimerRef.current) window.clearTimeout(hoverCommentTimerRef.current)
  }, [])

  useEffect(() => {
    const handleFindShortcut = (event: globalThis.KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'f') return
      event.preventDefault()
      event.stopPropagation()
      const activeElement = document.activeElement
      if (
        activeElement instanceof HTMLElement &&
        activeElement.matches('.sheet input.cell-edit, .side-fixed input[placeholder^="Ссылка"]')
      ) {
        suppressCellBlurRef.current = true
      }
      setFindOpen(true)
      requestAnimationFrame(() => findInputRef.current?.focus())
    }
    window.addEventListener('keydown', handleFindShortcut, true)
    return () => window.removeEventListener('keydown', handleFindShortcut, true)
  }, [])

  useEffect(() => {
    if (!resizingHistory) return
    const resize = (event: PointerEvent) => {
      const isRight = historyPosition === 'right'
      const viewportSize = isRight ? window.innerWidth : window.innerHeight
      const maxSize = isRight ? Math.min(760, viewportSize * 0.55) : Math.min(600, viewportSize * 0.6)
      const minSize = isRight ? Math.min(280, viewportSize * 0.35) : 140
      const requestedSize = isRight ? window.innerWidth - event.clientX : window.innerHeight - event.clientY
      const nextSize = Math.round(Math.max(minSize, Math.min(maxSize, requestedSize)))
      onHistorySizeChange(historyPosition, nextSize)
    }
    const stopResizing = () => setResizingHistory(false)
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = historyPosition === 'right' ? 'col-resize' : 'row-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', resize)
    window.addEventListener('pointerup', stopResizing)
    window.addEventListener('pointercancel', stopResizing)
    return () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener('pointermove', resize)
      window.removeEventListener('pointerup', stopResizing)
      window.removeEventListener('pointercancel', stopResizing)
    }
  }, [historyPosition, resizingHistory])

  useEffect(() => {
    if (findOpen) findInputRef.current?.focus()
  }, [findOpen])

  useEffect(() => {
    setFindIndex((index) => Math.min(index, Math.max(findResults.length - 1, 0)))
  }, [findResults.length])

  useEffect(() => {
    if (!findOpen || !activeFindResult) return
    findTargetsRef.current.get(activeFindResult.id)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [findOpen, activeFindResult])

  useEffect(() => {
    if (!selection) return
    const current = cells.get(`${selection.parameterKey}:${selection.columnKey}`)
    setEditValue(current?.display || current?.draft_value || current?.value || '')
    setLink(current?.hyperlink || '')
  }, [selection, cells])

  useEffect(() => {
    const node = gridRef.current?.querySelector('td.value.selected')
    node?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selection])

  useEffect(() => {
    setTableMode('view')
    setStructureEdit(false)
    setCommentMode(false)
  }, [workbook?.id, workbook?.is_primary])

  useEffect(() => {
    const selectedColumn = catalog?.columns.find((item) => item.key === columnKey)
    if (selectedColumn) {
      setColumnLabel(selectedColumn.label)
      return
    }
    const firstColumn = catalog?.columns[0]
    setColumnKey(firstColumn?.key || '')
    setColumnLabel(firstColumn?.label || '')
  }, [catalog, columnKey])

  if (!catalog || !workbook) {
    return (
      <div className="tab-page">
        <div className="hint">Сначала выберите объект на вкладке «Объект и треугольники».</div>
      </div>
    )
  }

  const activeCatalog = catalog
  const selectedCell = selection
    ? cells.get(`${selection.parameterKey}:${selection.columnKey}`)
    : undefined
  const selectedParam = activeCatalog.parameters.find((item) => item.key === selection?.parameterKey)
  const selectedCol = activeCatalog.columns.find((item) => item.key === selection?.columnKey)
  const editing = tableMode === 'edit' && canWrite && !workbook.is_primary
  const locked = Boolean(selectedCell?.locked || selectedCell?.unified) || !editing
  const readOnly = busy || locked

  async function persistDraft(
    target: Selection,
    value: string,
    hyperlink: string | null,
  ): Promise<boolean> {
    const existing = pendingDraftRef.current
    if (existing) {
      const sameDraft =
        existing.selection.parameterKey === target.parameterKey &&
        existing.selection.columnKey === target.columnKey &&
        existing.value === value &&
        existing.hyperlink === hyperlink
      if (sameDraft) return existing.promise
      if (!(await existing.promise)) return false
    }

    const promise = onDraft(target.parameterKey, target.columnKey, value, hyperlink)
    const pending = { selection: target, value, hyperlink, promise }
    pendingDraftRef.current = pending
    try {
      return await promise
    } finally {
      if (pendingDraftRef.current === pending) pendingDraftRef.current = null
    }
  }

  async function saveCurrentProject() {
    const selected = selection
    if (editing && selected) {
      const pending = pendingDraftRef.current
      const pendingIsCurrent = Boolean(
        pending &&
          pending.selection.parameterKey === selected.parameterKey &&
          pending.selection.columnKey === selected.columnKey &&
          pending.value === editValue &&
          pending.hyperlink === (link || null),
      )
      if (pending && !(await pending.promise)) return

      const current = cells.get(`${selected.parameterKey}:${selected.columnKey}`)
      if (
        !pendingIsCurrent &&
        (editValue !== (current?.display || '') || link !== (current?.hyperlink || ''))
      ) {
        if (!(await persistDraft(selected, editValue, link || null))) return
      }
    }
    await onSaveProject()
  }

  function selectCell(target: Selection) {
    const unchanged =
      selection?.parameterKey === target.parameterKey && selection.columnKey === target.columnKey
    if (unchanged) return
    setSelection(target)
    if (historyPanelOpen) onSelectCell(target)
  }

  function startCellEditing(target: Selection) {
    const cell = cells.get(`${target.parameterKey}:${target.columnKey}`)
    const parameter = activeCatalog.parameters.find((item) => item.key === target.parameterKey)
    if (
      !workbook || workbook.is_primary || !canWrite || busy || parameter?.row_kind !== 'editable' ||
      cell?.locked || cell?.unified
    ) return
    selectCell(target)
    setStructureEdit(false)
    setTableMode('edit')
    setContextMenu(null)
    requestAnimationFrame(() => {
      gridRef.current?.querySelector<HTMLElement>(
        'td.value.selected input.cell-edit, td.value.selected .cell-dict-btn',
      )?.focus({ preventScroll: true })
    })
  }

  function hideHoveredCellComment() {
    hoveredCellKeyRef.current = null
    if (hoverCommentTimerRef.current) window.clearTimeout(hoverCommentTimerRef.current)
    hoverCommentTimerRef.current = null
    const tooltip = cellCommentTooltipRef.current
    if (tooltip) {
      tooltip.hidden = true
      tooltip.setAttribute('aria-hidden', 'true')
      tooltip.textContent = ''
    }
  }

  function showCellComment(element: HTMLTableCellElement, comment: string) {
    const tooltip = cellCommentTooltipRef.current
    const area = sheetAreaRef.current
    if (!tooltip || !area) return
    tooltip.textContent = comment
    tooltip.hidden = false
    tooltip.setAttribute('aria-hidden', 'false')
    const areaBounds = area.getBoundingClientRect()
    const cellBounds = element.getBoundingClientRect()
    const tooltipWidth = tooltip.offsetWidth
    const tooltipHeight = tooltip.offsetHeight
    const left = Math.max(8, Math.min(cellBounds.left - areaBounds.left, areaBounds.width - tooltipWidth - 8))
    const below = cellBounds.bottom - areaBounds.top + 6
    const top = below + tooltipHeight <= areaBounds.height - 8
      ? below
      : Math.max(8, cellBounds.top - areaBounds.top - tooltipHeight - 6)
    tooltip.style.left = `${left}px`
    tooltip.style.top = `${top}px`
  }

  function handleCellMouseEnter(target: Selection, element: HTMLTableCellElement) {
    hideHoveredCellComment()
    if (!workbook) return

    const cell = cells.get(`${target.parameterKey}:${target.columnKey}`)
    if (!cell?.updated_at && !cell?.last_change_id) return
    const key = `${workbook.id}:${target.parameterKey}:${target.columnKey}`
    const cacheKey = `${target.parameterKey}:${target.columnKey}`
    hoveredCellKeyRef.current = key
    if (cellCommentCacheRef.current.has(cacheKey)) {
      const cachedComment = cellCommentCacheRef.current.get(cacheKey)
      if (cachedComment) showCellComment(element, cachedComment)
      return
    }

    hoverCommentTimerRef.current = window.setTimeout(() => {
      void onLoadCellComment(target.parameterKey, target.columnKey)
        .then((latestComment) => {
          const normalizedComment = latestComment?.trim() || null
          cellCommentCacheRef.current.set(cacheKey, normalizedComment)
          if (normalizedComment && hoveredCellKeyRef.current === key) {
            showCellComment(element, normalizedComment)
          }
        })
        .catch(() => cellCommentCacheRef.current.set(cacheKey, null))
    }, 350)
  }

  function moveTo(key: string) {
    const next = nextCell(activeCatalog, cells, selection, key)
    if (!next) return
    if (
      editing &&
      selection &&
      !readOnly &&
      (editValue !== (selectedCell?.display || '') || link !== (selectedCell?.hyperlink || ''))
    ) {
      void persistDraft(selection, editValue, link || null)
    }
    selectCell(next)
  }

  function registerFindTarget(id: string, node: HTMLElement | null) {
    if (node) findTargetsRef.current.set(id, node)
    else findTargetsRef.current.delete(id)
  }

  function getFindTargetRef(id: string) {
    const existingRef = findTargetRefsRef.current.get(id)
    if (existingRef) return existingRef
    const targetRef = (node: HTMLElement | null) => registerFindTarget(id, node)
    findTargetRefsRef.current.set(id, targetRef)
    return targetRef
  }

  function moveFind(direction: number) {
    if (!findResults.length) return
    setFindIndex((index) => (index + direction + findResults.length) % findResults.length)
  }

  function closeFind() {
    setFindOpen(false)
    setFindQuery('')
    requestAnimationFrame(() => {
      const editor = gridRef.current?.querySelector<HTMLElement>(
        'td.value.selected input.cell-edit, td.value.selected .cell-dict-btn',
      )
      if (editor) editor.focus()
      else gridRef.current?.focus()
    })
  }

  function handleFindInputKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeFind()
      return
    }
    if (event.key === 'Enter' || event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      moveFind(event.key === 'ArrowUp' || (event.key === 'Enter' && event.shiftKey) ? -1 : 1)
    }
  }

  function handleGridKey(event: KeyboardEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement | null
    if (target?.closest('.cell-dict-btn, .cell-dict-list, input.cell-edit')) return
    const nav =
      event.key === 'Tab'
        ? event.shiftKey
          ? 'ShiftTab'
          : 'Tab'
        : event.key
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab', 'ShiftTab'].includes(nav)) return
    event.preventDefault()
    moveTo(nav)
  }

  function handleContextMenu(event: MouseEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement
    const cell = target.closest<HTMLTableCellElement>('td.value[data-parameter-key][data-column-key]')
    if (!cell && target.closest('input, textarea, select, button, a, [contenteditable="true"]')) return
    event.preventDefault()
    const nextSelection = cell
      ? {
          parameterKey: cell.dataset.parameterKey || '',
          columnKey: cell.dataset.columnKey || '',
        }
      : null
    if (nextSelection?.parameterKey && nextSelection.columnKey) {
      selectCell(nextSelection)
    }
    setContextMenu({ x: event.clientX, y: event.clientY, selection: nextSelection })
  }

  async function saveCellComment() {
    if (!selection || !cellComment.trim()) return
    const target = draftSaveTarget || selection
    const { parameterKey, columnKey } = target
    const saved = draftSaveTarget
      ? await onConfirm(
          parameterKey,
          columnKey,
          cells.get(`${parameterKey}:${columnKey}`)?.draft_value ||
            cells.get(`${parameterKey}:${columnKey}`)?.display || '',
          cellComment.trim(),
          cells.get(`${parameterKey}:${columnKey}`)?.hyperlink || null,
        )
      : await onAddComment(parameterKey, columnKey, cellComment.trim())
    if (saved) {
      setCellComment('')
      setCommentMode(false)
      setDraftSaveTarget(null)
    }
  }

  function showCellHistory(target: Selection) {
    setSelection(target)
    onSelectCell(target)
    onShowHistory()
    setContextMenu(null)
  }

  function startCellComment(target: Selection) {
    if (workbook?.is_primary || !canWrite || busy || cells.get(`${target.parameterKey}:${target.columnKey}`)?.locked) return
    setDraftSaveTarget(null)
    setSelection(target)
    onSelectCell(target)
    onShowHistory()
    setCellComment('')
    setCommentMode(true)
    setContextMenu(null)
    requestAnimationFrame(() => commentInputRef.current?.focus())
  }

  async function startDraftSave(target: Selection) {
    const key = `${target.parameterKey}:${target.columnKey}`
    const current = cells.get(key)
    if (workbook?.is_primary || !canWrite || busy || current?.locked || current?.unified) return
    const isEditingThisCell = editing && selection?.parameterKey === target.parameterKey && selection.columnKey === target.columnKey
    if (
      isEditingThisCell &&
      (editValue !== (current?.display || '') || link !== (current?.hyperlink || '')) &&
      !(await persistDraft(target, editValue, link || null))
    ) return
    setDraftSaveTarget(target)
    setSelection(target)
    onSelectCell(target)
    onShowHistory()
    setCellComment('')
    setCommentMode(true)
    setContextMenu(null)
    requestAnimationFrame(() => commentInputRef.current?.focus())
  }

  function canSaveDraft(target: Selection): boolean {
    const cell = cells.get(`${target.parameterKey}:${target.columnKey}`)
    const hasUnsavedDraft = unsaved.some(
      (item) => item.parameter_key === target.parameterKey && item.column_key === target.columnKey,
    )
    const isChangedEditor =
      editing &&
      selection?.parameterKey === target.parameterKey &&
      selection.columnKey === target.columnKey &&
      (editValue !== (cell?.display || '') || link !== (cell?.hyperlink || ''))
    return Boolean(cell?.status === 'draft' || hasUnsavedDraft || isChangedEditor)
  }

  function openCellFind(target: Selection) {
    const cell = cells.get(`${target.parameterKey}:${target.columnKey}`)
    setFindQuery(cell?.display || cell?.draft_value || cell?.value || '')
    setFindIndex(0)
    setFindOpen(true)
    setContextMenu(null)
    requestAnimationFrame(() => findInputRef.current?.focus())
  }

  return (
    <div className="tab-page" onContextMenu={handleContextMenu}>
      <div className="object-table-header">
        {objectName ? <h2 className="object-table-title">{objectName}</h2> : <span />}
        <div className="object-actions">
          <button
            type="button"
            className="win-btn"
            disabled={busy || !canWrite}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => void saveCurrentProject()}
          >
            Сохранить проект
          </button>
          <label className={`win-btn${busy || !canWrite ? ' disabled' : ''}`}>
            Импортировать .xlsx
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              disabled={busy || !canWrite}
              hidden
              onChange={(event) => {
                const file = event.currentTarget.files?.[0]
                event.currentTarget.value = ''
                if (file) onImportWorkbook(file)
              }}
            />
          </label>
          <button
            type="button"
            className="win-btn"
            disabled={busy || editing || !workbook}
            title={editing ? 'Завершите редактирование ячейки перед выгрузкой' : 'Выгрузить текущий лист в Excel'}
            onClick={onExportCurrent}
          >
            Выгрузить лист
          </button>
          <button
            type="button"
            className="win-btn"
            disabled={busy || editing || !workbook}
            title={editing ? 'Завершите редактирование ячейки перед выгрузкой' : 'Выгрузить все листы проекта и проверки в Excel'}
            onClick={onExportAll}
          >
            Выгрузить всё
          </button>
          <button
            type="button"
            className="win-btn"
            disabled={busy}
            onClick={onComposeReport}
          >
            Составить отчет
          </button>
        </div>
      </div>
      <div className="toolbar" data-guide="guide-colors">
        <div className="view-tabs table-mode-tabs" data-guide="guide-table-mode">
          <button
            type="button"
            className={tableMode === 'view' ? 'active' : ''}
            aria-label="Режим просмотра"
            aria-pressed={tableMode === 'view'}
            title="Режим просмотра"
            onClick={() => {
              setTableMode('view')
              setStructureEdit(false)
            }}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          {!workbook.is_primary ? (
            <button
              type="button"
              className={tableMode === 'edit' ? 'active' : ''}
              aria-label="Режим редактирования"
              aria-pressed={tableMode === 'edit'}
              title="Режим редактирования"
              disabled={!canWrite}
              onClick={() => setTableMode('edit')}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="m4 16.5-.8 4.3 4.3-.8L20 7.5 16.5 4 4 16.5Z" />
                <path d="m14.8 5.7 3.5 3.5" />
              </svg>
            </button>
          ) : null}
        </div>
        <span className="hint">
          {workbook.is_primary
            ? 'Основной лист доступен только для просмотра.'
            : editing
              ? 'Жёлтый — черновик, зелёный — сохранено, серый — группа или заблокировано правилом.'
              : 'Просмотр: значения не меняются. Чтобы править ячейки, включите режим редактирования.'}
        </span>
        {unsaved.length > 0 ? (
          <span className="warn">Несохранено ячеек: {unsaved.length}</span>
        ) : (
          <span className="hint">Несохранённых ячеек нет</span>
        )}
        {!canWrite ? <span className="warn">Нет прав на запись</span> : null}
        {editing ? (
          <button
            type="button"
            className="win-btn"
            data-guide="guide-add-param"
            onClick={() => setStructureEdit((prev) => !prev)}
          >
            {structureEdit ? 'Готово' : 'Редактировать структуру'}
          </button>
        ) : null}
      </div>
      {structureEdit && editing ? (
        <div className="toolbar">
          <span className="hint">Выберите строку слева. Можно менять имя, единицы, уровень, добавлять и удалять.</span>
          <input
            type="text"
            placeholder="Наименование"
            value={structLabel}
            onChange={(event) => setStructLabel(event.target.value)}
          />
          <input
            type="text"
            placeholder="Ед. изм."
            value={structUnit}
            onChange={(event) => setStructUnit(event.target.value)}
            style={{ width: 90 }}
          />
          <label>
            Уровень
            <select
              value={structIndent}
              onChange={(event) => setStructIndent(Number(event.target.value))}
            >
              <option value={0}>0 — группа</option>
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>
          </label>
          <button
            type="button"
            className="win-btn"
            disabled={busy || !structKey || !structLabel.trim()}
            onClick={() =>
              onUpdateParameter(structKey, {
                label: structLabel.trim(),
                unit: structUnit.trim(),
                indent: structIndent,
                row_kind: structIndent === 0 ? 'section' : 'editable',
              })
            }
          >
            Сохранить строку
          </button>
          <button
            type="button"
            className="win-btn"
            disabled={busy || !structLabel.trim()}
            onClick={() =>
              onAddParameter({
                label: structLabel.trim(),
                unit: structUnit.trim(),
                indent: structIndent,
                row_kind: structIndent === 0 ? 'section' : 'editable',
                insert_after: structKey || undefined,
              })
            }
          >
            Добавить
          </button>
          <button
            type="button"
            className="win-btn"
            disabled={busy || !structKey}
            onClick={() => {
              const parent = activeCatalog.parameters.find((item) => item.key === structKey)
              onAddParameter({
                label: structLabel.trim() || 'Новый параметр',
                unit: structUnit.trim(),
                indent: Math.min((parent?.indent ?? 0) + 1, 2),
                row_kind: 'editable',
                insert_after: structKey,
                group: parent?.key,
              })
            }}
          >
            Добавить вложенный
          </button>
          <button
            type="button"
            className="win-btn"
            disabled={busy || !structKey}
            onClick={() => {
              if (!window.confirm('Удалить выбранную строку из этой сводки?')) return
              onDeleteParameter(structKey)
              setStructKey('')
            }}
          >
            Удалить
          </button>
        </div>
      ) : null}
      {structureEdit && editing ? (
        <div className="toolbar">
          <strong>Столбцы листа</strong>
          <select
            aria-label="Выбрать столбец для редактирования"
            value={columnKey}
            onChange={(event) => setColumnKey(event.target.value)}
            style={{ minWidth: 180 }}
          >
            {activeCatalog.columns.map((column) => (
              <option key={column.key} value={column.key}>{column.label}</option>
            ))}
          </select>
          <input
            type="text"
            aria-label="Новое наименование выбранного столбца"
            placeholder="Наименование столбца"
            value={columnLabel}
            onChange={(event) => setColumnLabel(event.target.value)}
          />
          <button
            type="button"
            className="win-btn"
            disabled={busy || !columnKey || !columnLabel.trim()}
            onClick={() => onUpdateColumn(columnKey, columnLabel.trim())}
          >
            Сохранить название
          </button>
          <button
            type="button"
            className="win-btn"
            disabled={busy || !columnKey}
            onClick={() => {
              const column = activeCatalog.columns.find((item) => item.key === columnKey)
              if (!window.confirm(`Удалить столбец «${column?.label || ''}» с этого листа? Значения можно вернуть отменой действия.`)) return
              onDeleteColumn(columnKey)
              if (selection?.columnKey === columnKey) setSelection(null)
              setColumnKey(activeCatalog.columns.find((item) => item.key !== columnKey)?.key || '')
            }}
          >
            Удалить столбец
          </button>
          <input
            type="text"
            aria-label="Наименование нового столбца"
            placeholder="Новый столбец"
            value={newColumnLabel}
            onChange={(event) => setNewColumnLabel(event.target.value)}
          />
          <button
            type="button"
            className="win-btn"
            disabled={busy || !newColumnLabel.trim()}
            onClick={() => {
              onAddColumn(newColumnLabel.trim())
              setNewColumnLabel('')
            }}
          >
            Добавить столбец
          </button>
        </div>
      ) : null}
      <div className={`table-workspace history-${historyPosition}`}>
        <div className="sheet-area" ref={sheetAreaRef}>
        {findOpen ? (
          <div className="table-find-panel" role="search">
            <label htmlFor="table-find-input">Найти</label>
            <input
              ref={findInputRef}
              id="table-find-input"
              type="search"
              value={findQuery}
              aria-label="Найти в таблице ИД"
              onChange={(event) => {
                setFindQuery(event.target.value)
                setFindIndex(0)
              }}
              onKeyDown={handleFindInputKey}
            />
            <span className="table-find-count" aria-live="polite">
              {findQuery.trim() ? `${findResults.length ? findIndex + 1 : 0} из ${findResults.length}` : 'Введите текст'}
            </span>
            <button type="button" className="win-btn" disabled={!findResults.length} aria-label="Предыдущее совпадение" onClick={() => moveFind(-1)}>↑</button>
            <button type="button" className="win-btn" disabled={!findResults.length} aria-label="Следующее совпадение" onClick={() => moveFind(1)}>↓</button>
            <button type="button" className="win-btn" aria-label="Закрыть поиск" onClick={closeFind}>Закрыть</button>
          </div>
        ) : null}
        <div className="sheet-tabs" role="tablist" aria-label="Листы таблицы ИД">
          {sheets.map((sheet) => (
            <button
              key={sheet.id}
              type="button"
              role="tab"
              aria-selected={workbook.id === sheet.id}
              aria-label={`${sheet.name}${sheet.is_primary ? ', основной лист' : ''}`}
              className={workbook.id === sheet.id ? 'active' : ''}
              disabled={busy}
              onClick={() => onSelectSheet(sheet.id)}
              onContextMenu={(event) => {
                event.preventDefault()
                event.stopPropagation()
                setContextMenu({ x: event.clientX, y: event.clientY, selection: null, sheetId: sheet.id })
              }}
            >
              {sheet.name}{sheet.is_primary ? ' · основной' : ''}
            </button>
          ))}
        </div>
        <div
          className="grid-wrap"
          data-guide="guide-sheet"
          ref={gridRef}
          tabIndex={0}
          onKeyDown={handleGridKey}
          onScroll={hideHoveredCellComment}
        >
          <table className={`sheet${structureEdit ? ' structure-edit' : ''}${editing ? ' edit-mode' : ' view-mode'}`}>
            <thead>
            {activeCatalog.columns.length > 0 ? (
              <>
                <tr>
                  <th className="param" rowSpan={2}>Наименование параметра</th>
                  <th className="unit" rowSpan={2}>Ед. изм.</th>
                  <th className="step-group" colSpan={activeCatalog.columns.length}>Ступени</th>
                </tr>
                <tr>
                  {activeCatalog.columns.map((col) => {
                    const findId = `column:${col.key}`
                    const findActive = activeFindResult?.id === findId
                    return (
                      <th
                        key={col.key}
                        ref={findOpen ? getFindTargetRef(findId) : undefined}
                        className={`${selection?.columnKey === col.key ? 'col-hi' : ''}${findActive ? ' find-current' : ''}`}
                      >
                        {highlightSearchText(col.label, visibleFindQuery, findActive)}
                      </th>
                    )
                  })}
                </tr>
              </>
            ) : (
              <tr>
                <th className="param">Наименование параметра</th>
                <th className="unit">Ед. изм.</th>
              </tr>
            )}
          </thead>
          <tbody>
            {activeCatalog.parameters.map((param) => {
              const inRow = selection?.parameterKey === param.key
              return (
              <tr
                key={param.key}
                className={`${param.row_kind === 'section' || param.row_kind === 'computed' ? 'section' : ''}${inRow ? ' row-active' : ''}`.trim()}
              >
                <th
                  ref={findOpen ? getFindTargetRef(`parameter:${param.key}`) : undefined}
                  className={`param indent-${param.indent}${inRow ? ' row-hi' : ''}${structureEdit && structKey === param.key ? ' selected' : ''}${activeFindResult?.id === `parameter:${param.key}` ? ' find-current' : ''}`}
                  onClick={() => {
                    if (!structureEdit) return
                    setStructKey(param.key)
                    setStructLabel(displayLabel(param.label, param.unit))
                    setStructUnit(param.unit || '')
                    setStructIndent(param.indent)
                  }}
                >
                  {highlightSearchText(displayLabel(param.label, param.unit), visibleFindQuery, activeFindResult?.id === `parameter:${param.key}`)}
                </th>
                <td
                  ref={findOpen ? getFindTargetRef(`unit:${param.key}`) : undefined}
                  className={`unit${inRow ? ' row-hi' : ''}${activeFindResult?.id === `unit:${param.key}` ? ' find-current' : ''}`}
                >
                  {param.row_kind === 'editable'
                    ? highlightSearchText(param.unit || '', visibleFindQuery, activeFindResult?.id === `unit:${param.key}`)
                    : ''}
                </td>
                {activeCatalog.columns.map((col) => {
                  const inCol = selection?.columnKey === col.key
                  const axis = `${inRow ? ' row-hi' : ''}${inCol ? ' col-hi' : ''}`
                  if (param.row_kind !== 'editable') {
                    return <td key={col.key} className={`computed${axis}`} />
                  }
                  const cell = cells.get(`${param.key}:${col.key}`)
                  const selected = inRow && inCol
                  const cellLocked = Boolean(cell?.locked || cell?.unified) || !editing || busy
                  const status = cell?.locked ? 'computed' : cell?.status || 'empty'
                  const cellOptions = (param.options && param.options.length > 0
                    ? param.options
                    : cell?.options) || []
                  const findId = `cell:${param.key}:${col.key}`
                  const findActive = activeFindResult?.id === findId
                  return (
                    <td
                      key={col.key}
                      ref={findOpen ? getFindTargetRef(findId) : undefined}
                      data-parameter-key={param.key}
                      data-column-key={col.key}
                      className={`value ${status}${selected ? ' selected' : ''}${cell?.unified ? ' unified' : ''}${axis}${findActive ? ' find-current' : ''}`}
                      title={cell?.unified ? 'Унифицировано: изменение запрещено' : undefined}
                      onClick={() => {
                        const next = { parameterKey: param.key, columnKey: col.key }
                        selectCell(next)
                        if (!editing) gridRef.current?.focus()
                      }}
                      onMouseEnter={(event) =>
                        handleCellMouseEnter(
                          { parameterKey: param.key, columnKey: col.key },
                          event.currentTarget,
                        )
                      }
                      onMouseLeave={hideHoveredCellComment}
                    >
                      {selected && editing && !cellLocked ? (
                        cellOptions.length > 0 ? (
                          <CellDictSelect
                            key={`${param.key}:${col.key}`}
                            value={editValue}
                            options={cellOptions}
                            onPick={(next) => {
                              setEditValue(next)
                              void persistDraft({ parameterKey: param.key, columnKey: col.key }, next, link || null)
                            }}
                            onNavigate={(key) => moveTo(key)}
                          />
                        ) : (
                          <input
                            className="cell-edit"
                            type="text"
                            autoFocus
                            value={editValue}
                            onChange={(event) => setEditValue(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onBlur={() => {
                              if (suppressCellBlurRef.current) {
                                suppressCellBlurRef.current = false
                                return
                              }
                              if (
                                editValue !== (cell?.display || '') ||
                                link !== (cell?.hyperlink || '')
                              ) {
                                void persistDraft(
                                  { parameterKey: param.key, columnKey: col.key },
                                  editValue,
                                  link || null,
                                )
                              }
                            }}
                            onKeyDown={(event) => {
                              if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
                                if (editValue !== (cell?.display || '')) {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  setEditValue(cell?.display || '')
                                } else {
                                  event.preventDefault()
                                }
                                return
                              }
                              if (event.key === 'Enter') {
                                event.currentTarget.blur()
                                return
                              }
                              if (event.key === 'Escape') {
                                setEditValue(cell?.display || '')
                                event.currentTarget.blur()
                                return
                              }
                              const input = event.currentTarget
                              const start = input.selectionStart ?? 0
                              const end = input.selectionEnd ?? 0
                              const caret = start === end
                              if (event.key === 'ArrowUp' || event.key === 'ArrowDown' || event.key === 'Tab') {
                                event.preventDefault()
                                event.stopPropagation()
                                moveTo(event.key === 'Tab' && event.shiftKey ? 'ShiftTab' : event.key)
                                return
                              }
                              if (event.key === 'ArrowLeft' && caret && start === 0) {
                                event.preventDefault()
                                event.stopPropagation()
                                moveTo('ArrowLeft')
                                return
                              }
                              if (event.key === 'ArrowRight' && caret && end === input.value.length) {
                                event.preventDefault()
                                event.stopPropagation()
                                moveTo('ArrowRight')
                              }
                            }}
                          />
                        )
                      ) : (
                        <span className="cell-text">
                          {cell?.hyperlink ? (
                            <a href={cell.hyperlink} onClick={(event) => event.preventDefault()}>
                              {highlightSearchText(cell.display || '', visibleFindQuery, findActive)}
                            </a>
                          ) : (
                            highlightSearchText(cell?.display || '\u00a0', visibleFindQuery, findActive)
                          )}
                          {editing && cellOptions.length > 0 ? <span className="cell-dict-mark">▾</span> : null}
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
              )
            })}
          </tbody>
        </table>
        </div>
        <div
          ref={cellCommentTooltipRef}
          className="cell-comment-tooltip"
          role="tooltip"
          aria-hidden="true"
          hidden
        />
      </div>
      {contextMenu ? createPortal(
        <div
          ref={contextMenuRef}
          className="table-context-menu"
          role="menu"
          aria-label="Действия"
          style={{
            left: Math.max(8, Math.min(contextMenu.x, window.innerWidth - 260)),
            top: Math.max(8, Math.min(contextMenu.y, window.innerHeight - (contextMenu.sheetId ? 210 : contextMenu.selection ? 270 : contextMenu.area ? 70 : 90))),
          }}
          onContextMenu={(event) => event.preventDefault()}
        >
          {contextMenu.sheetId && contextMenuSheet ? (
            <>
              <button type="button" role="menuitem" disabled={!canWrite || busy || contextMenuSheet.is_primary} onClick={() => {
                setContextMenu(null)
                onRenameSheet(contextMenuSheet.id)
              }}>
                Переименовать лист
              </button>
              {contextMenuSheet.is_primary ? (
                <button type="button" role="menuitem" disabled={!canWrite || busy} onClick={() => {
                  setContextMenu(null)
                  onUnsetPrimarySheet(contextMenuSheet.id)
                }}>
                  Сделать обычным листом
                </button>
              ) : (
                <button type="button" role="menuitem" disabled={!canWrite || busy} onClick={() => {
                  setContextMenu(null)
                  onSetPrimarySheet(contextMenuSheet.id)
                }}>
                  Сделать основным
                </button>
              )}
              <button type="button" role="menuitem" disabled={!canWrite || busy} onClick={() => {
                setContextMenu(null)
                onCopySheet(contextMenuSheet.id)
              }}>
                Копировать лист
              </button>
              {contextMenuSheet.id !== (workbook.parent_workbook_id || workbook.id) ? (
                <button type="button" role="menuitem" disabled={!canWrite || busy || contextMenuSheet.is_primary} onClick={() => {
                  setContextMenu(null)
                  onDeleteSheet(contextMenuSheet.id)
                }}>
                  Удалить лист
                </button>
              ) : null}
            </>
          ) : contextMenu.area === 'history' ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onHideHistory()
                setContextMenu(null)
              }}
            >
              Скрыть историю
            </button>
          ) : contextMenu.selection ? (
            <>
              <button
                type="button"
                role="menuitem"
                disabled={
                  workbook.is_primary || !canWrite || busy || Boolean(cells.get(
                    `${contextMenu.selection.parameterKey}:${contextMenu.selection.columnKey}`,
                  )?.locked || cells.get(
                    `${contextMenu.selection.parameterKey}:${contextMenu.selection.columnKey}`,
                  )?.unified)
                }
                onClick={() => startCellEditing(contextMenu.selection!)}
              >
                Изменить данные в ячейке
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => openCellFind(contextMenu.selection!)}
              >
                Найти в таблице
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => showCellHistory(contextMenu.selection!)}
              >
                Показать историю
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={workbook.is_primary || !canWrite || busy}
                onClick={() => {
                  const target = contextMenu.selection!
                  const cell = cells.get(`${target.parameterKey}:${target.columnKey}`)
                  void onToggleUnification(target.parameterKey, target.columnKey, !cell?.unified)
                  setContextMenu(null)
                }}
              >
                {cells.get(
                  `${contextMenu.selection.parameterKey}:${contextMenu.selection.columnKey}`,
                )?.unified
                  ? 'Снять унификацию'
                  : 'Установить унификацию'}
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={
                  workbook.is_primary || !canWrite || busy || Boolean(cells.get(
                    `${contextMenu.selection.parameterKey}:${contextMenu.selection.columnKey}`,
                  )?.locked)
                }
                onClick={() => startCellComment(contextMenu.selection!)}
              >
                Оставить комментарий
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={
                  workbook.is_primary || !canWrite || busy || !canSaveDraft(contextMenu.selection!) || Boolean(cells.get(
                    `${contextMenu.selection.parameterKey}:${contextMenu.selection.columnKey}`,
                  )?.locked || cells.get(
                    `${contextMenu.selection.parameterKey}:${contextMenu.selection.columnKey}`,
                  )?.unified)
                }
                onClick={() => void startDraftSave(contextMenu.selection!)}
              >
                Сохранить черновик
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={workbook.is_primary || !canWrite || busy || unsaved.length === 0}
                onClick={() => {
                  onSaveAllDrafts()
                  setContextMenu(null)
                }}
              >
                Сохранить все черновики
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setFindOpen(true)
                  setContextMenu(null)
                  requestAnimationFrame(() => findInputRef.current?.focus())
                }}
              >
                Найти в таблице
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onShowHistory()
                  setContextMenu(null)
                }}
              >
                Показать историю
              </button>
            </>
          )}
        </div>,
        document.body,
      ) : null}
      {historyPanelOpen ? (
        <>
          <div
            className={`history-resizer ${historyPosition}`}
            role="separator"
            aria-orientation={historyPosition === 'right' ? 'vertical' : 'horizontal'}
            aria-label="Изменить размер панели истории"
            aria-valuenow={historySize}
            tabIndex={0}
            onPointerDown={(event) => {
              event.preventDefault()
              setResizingHistory(true)
            }}
            onKeyDown={(event) => {
              const increase = historyPosition === 'right' ? 'ArrowLeft' : 'ArrowUp'
              const decrease = historyPosition === 'right' ? 'ArrowRight' : 'ArrowDown'
              if (event.key === increase || event.key === decrease) {
                event.preventDefault()
                const delta = event.key === increase ? 16 : -16
                const minSize = historyPosition === 'right' ? Math.min(280, window.innerWidth * 0.35) : 140
                const maxSize = historyPosition === 'right' ? Math.min(760, window.innerWidth * 0.55) : 600
                onHistorySizeChange(
                  historyPosition,
                  Math.max(minSize, Math.min(maxSize, historySizes[historyPosition] + delta)),
                )
              }
            }}
          />
          <aside
            className={`side history-${historyPosition}`}
            data-guide="guide-edit"
            style={historyPosition === 'right' ? { width: historySize } : { height: historySize }}
            onContextMenu={(event) => {
              event.preventDefault()
              event.stopPropagation()
              setContextMenu({ x: event.clientX, y: event.clientY, selection: null, area: 'history' })
            }}
          >
            <div className="history-panel-header">
              <strong>История изменений</strong>
            </div>
        {selection && selectedParam ? (
          <>
            <div className="side-fixed">
              <div className="toolbar">
                <strong>
                  {displayLabel(selectedParam.label, selectedParam.unit)}
                  {selectedParam.unit ? `, ${selectedParam.unit}` : ''} / ступень {selectedCol?.label}
                </strong>
                {editing ? (
                  <>
                    <input
                      type="text"
                      placeholder="Ссылка (прячется в номере)"
                      value={link}
                      disabled={readOnly}
                      onChange={(event) => setLink(event.target.value)}
                      onBlur={() => {
                        if (suppressCellBlurRef.current) {
                          suppressCellBlurRef.current = false
                          return
                        }
                        if (link !== (selectedCell?.hyperlink || '')) {
                          void persistDraft(selection, editValue, link || null)
                        }
                      }}
                      style={{ minWidth: 180 }}
                    />
                    <input
                      type="text"
                      placeholder="Комментарий (обязателен)"
                      value={comment}
                      disabled={!canWrite}
                      onChange={(event) => setComment(event.target.value)}
                      style={{ minWidth: 220 }}
                    />
                    <button
                      type="button"
                      className="win-btn"
                      disabled={readOnly || !comment.trim()}
                      onClick={() => {
                        onConfirm(
                          selection.parameterKey,
                          selection.columnKey,
                          editValue,
                          comment.trim(),
                          link || null,
                        )
                        setComment('')
                      }}
                    >
                      Сохранить значение
                    </button>
                    <button
                      type="button"
                      className="win-btn"
                      disabled={!canWrite || busy || selectedCell?.status !== 'draft'}
                      onClick={() => onDiscard(selection.parameterKey, selection.columnKey)}
                    >
                      Отменить черновик
                    </button>
                  </>
                ) : (
                  <span className="hint">Чтобы изменить значение, включите режим редактирования.</span>
                )}
              </div>
              {selectedCell?.unified ? (
                <div className="hint">Унификация включена. Изменение значения ячейки запрещено.</div>
              ) : selectedCell?.locked ? (
                <div className="hint">Поле автоматически заблокировано правилом унификации.</div>
              ) : null}
              {selectedCell?.hyperlink ? (
                <div className="hint">
                  Ссылка:{' '}
                  <a href={selectedCell.hyperlink} target="_blank" rel="noreferrer">
                    {selectedCell.hyperlink}
                  </a>
                </div>
              ) : null}
            </div>
            {commentMode && selection ? (
              <form
                className="cell-comment-composer"
                onSubmit={(event) => {
                  event.preventDefault()
                  void saveCellComment()
                }}
              >
                <label htmlFor="cell-history-comment">
                  {draftSaveTarget ? 'Комментарий для сохранения черновика' : 'Комментарий к ячейке'}
                </label>
                <textarea
                  ref={commentInputRef}
                  id="cell-history-comment"
                  value={cellComment}
                  disabled={busy}
                  onChange={(event) => setCellComment(event.target.value)}
                  placeholder="Введите комментарий"
                  rows={3}
                />
                <div className="cell-comment-actions">
                  <button type="submit" className="win-btn" disabled={busy || !cellComment.trim()}>
                    {draftSaveTarget ? 'Сохранить черновик' : 'Добавить комментарий'}
                  </button>
                  <button
                    type="button"
                    className="win-btn"
                    onClick={() => {
                      setCellComment('')
                      setCommentMode(false)
                      setDraftSaveTarget(null)
                    }}
                  >
                    Отмена
                  </button>
                </div>
              </form>
            ) : null}
            <div className="history-wrap">
              <table className="history">
                <thead>
                  <tr>
                    <th>Когда</th>
                    <th>Кто</th>
                    <th>Было</th>
                    <th>Стало</th>
                    <th>Комментарий</th>
                  </tr>
                </thead>
                <tbody>
                  {history.length === 0 ? (
                    <tr>
                      <td colSpan={5}>История пуста</td>
                    </tr>
                  ) : (
                    history.map((item) => (
                      <tr key={item.id}>
                        <td>{new Date(item.created_at).toLocaleString()}</td>
                        <td>{item.author}</td>
                        <td>{item.old_value || ''}</td>
                        <td>{item.new_value || ''}</td>
                        <td>{item.comment}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="hint">
            {editing
              ? 'Выберите ячейку, чтобы ввести значение, увидеть историю и сохранить.'
              : 'Выберите ячейку, чтобы увидеть историю. Правка доступна в режиме редактирования.'}
          </div>
        )}
          </aside>
        </>
      ) : null}
      </div>
    </div>
  )
}

export const TableTab = memo(TableTabContent, areTablePropsEqual)
