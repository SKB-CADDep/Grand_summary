import { useEffect, useMemo, useState } from 'react'
import type { Catalog, TriangleSheetData, TriangleSourceCell, WorkbookSheet } from '../types'

type SyncMode = 'selected' | 'all'

type Props = {
  sheets: TriangleSheetData[]
  targetSheets: WorkbookSheet[]
  canWrite: boolean
  busy: boolean
  onLoadCatalog: (sheetId: string) => Promise<Catalog>
  onSync: (
    targetSheetId: string,
    mode: SyncMode,
    cells: TriangleSourceCell[],
    targetParameterKey: string | null,
  ) => void
}

const MIN_ROW = 11
const MIN_COLUMN = 2

function cellKey(sheetKey: TriangleSheetData['key'], row: number, column: number) {
  return `${sheetKey}:${row}:${column}`
}

export function TriangleTab({
  sheets,
  targetSheets,
  canWrite,
  busy,
  onLoadCatalog,
  onSync,
}: Props) {
  const [activeKey, setActiveKey] = useState<TriangleSheetData['key']>(sheets[0]?.key || 'geometry')
  const [selected, setSelected] = useState<Record<string, TriangleSourceCell>>({})
  const writableTargets = useMemo(
    () => targetSheets.filter((sheet) => !sheet.is_primary),
    [targetSheets],
  )
  const [targetSheetId, setTargetSheetId] = useState('')
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [targetParameterKey, setTargetParameterKey] = useState('')

  const activeSheet = sheets.find((sheet) => sheet.key === activeKey) || sheets[0]
  const selectedList = Object.values(selected)

  useEffect(() => {
    if (!sheets.some((sheet) => sheet.key === activeKey) && sheets[0]) {
      setActiveKey(sheets[0].key)
    }
  }, [activeKey, sheets])

  useEffect(() => {
    if (!writableTargets.some((sheet) => sheet.id === targetSheetId)) {
      setTargetSheetId(writableTargets[0]?.id || '')
    }
  }, [targetSheetId, writableTargets])

  useEffect(() => {
    if (!targetSheetId) {
      setCatalog(null)
      return
    }
    let cancelled = false
    onLoadCatalog(targetSheetId)
      .then((next) => {
        if (!cancelled) setCatalog(next)
      })
      .catch(() => {
        if (!cancelled) setCatalog(null)
      })
    return () => {
      cancelled = true
    }
  }, [onLoadCatalog, targetSheetId])

  const parameters = useMemo(
    () => (catalog?.parameters || []).filter((item) => item.row_kind === 'editable'),
    [catalog],
  )

  function toggleCell(sheetKey: TriangleSheetData['key'], row: number, column: number) {
    if (row < MIN_ROW || column < MIN_COLUMN) return
    const key = cellKey(sheetKey, row, column)
    setSelected((current) => {
      if (current[key]) {
        const next = { ...current }
        delete next[key]
        return next
      }
      return { ...current, [key]: { sheet_key: sheetKey, row, column } }
    })
  }

  function isSourceCell(rowIndex: number, columnIndex: number) {
    return rowIndex + 1 >= MIN_ROW && columnIndex + 1 >= MIN_COLUMN
  }

  return (
    <div className="tab-page triangle-page">
      <h2 className="triangle-title">Треугольники</h2>
      <div className="triangle-subtabs" role="tablist">
        {sheets.map((sheet) => (
          <button
            key={sheet.key}
            type="button"
            role="tab"
            className={sheet.key === activeSheet?.key ? 'active' : ''}
            onClick={() => setActiveKey(sheet.key)}
          >
            {sheet.name}
          </button>
        ))}
      </div>
      <div className="triangle-sync-toolbar">
        <label>
          Лист ИД
          <select
            value={targetSheetId}
            disabled={busy || !writableTargets.length}
            onChange={(event) => setTargetSheetId(event.target.value)}
          >
            {writableTargets.length === 0 ? <option value="">Нет листа для записи</option> : null}
            {writableTargets.map((sheet) => (
              <option key={sheet.id} value={sheet.id}>
                {sheet.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Параметр для несопоставленных
          <select
            value={targetParameterKey}
            disabled={busy || !parameters.length}
            onChange={(event) => setTargetParameterKey(event.target.value)}
          >
            <option value="">Не задан</option>
            {parameters.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="win-btn"
          disabled={!canWrite || busy || !targetSheetId || selectedList.length === 0}
          onClick={() => onSync(targetSheetId, 'selected', selectedList, targetParameterKey || null)}
        >
          Перенести выделенное
        </button>
        <button
          type="button"
          className="win-btn"
          disabled={!canWrite || busy || !targetSheetId}
          onClick={() => onSync(targetSheetId, 'all', [], targetParameterKey || null)}
        >
          Перенести всё
        </button>
        <span className="triangle-selection-count">Выделено ячеек: {selectedList.length}</span>
        <span className="triangle-selection-hint">
          Клик по ячейке выделяет её для переноса. Основной лист ИД недоступен для записи.
        </span>
      </div>
      <div className="triangle-grid-wrap">
        {activeSheet ? (
          <table className="triangle-grid">
            <tbody>
              {activeSheet.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  <th className="triangle-row-number">{rowIndex + 1}</th>
                  {row.map((value, columnIndex) => {
                    const source = isSourceCell(rowIndex, columnIndex)
                    const key = cellKey(activeSheet.key, rowIndex + 1, columnIndex + 1)
                    return (
                      <td
                        key={columnIndex}
                        className={`${source ? 'triangle-source-cell' : ''}${selected[key] ? ' selected' : ''}`}
                        onClick={() => {
                          if (!source || busy) return
                          toggleCell(activeSheet.key, rowIndex + 1, columnIndex + 1)
                        }}
                      >
                        {value}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="hint">Нет импортированных листов треугольников.</div>
        )}
      </div>
    </div>
  )
}
