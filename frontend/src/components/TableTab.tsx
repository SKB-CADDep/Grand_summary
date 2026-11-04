import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { Catalog, Cell, CellChange, ParameterWrite, UnsavedCell, Workbook } from '../types'
import { CellDictSelect } from './CellDictSelect'

type Selection = { parameterKey: string; columnKey: string }

type Props = {
  catalog: Catalog | null
  workbook: Workbook | null
  unsaved: UnsavedCell[]
  history: CellChange[]
  busy: boolean
  canWrite: boolean
  onDraft: (parameterKey: string, columnKey: string, value: string, hyperlink: string | null) => void
  onConfirm: (
    parameterKey: string,
    columnKey: string,
    value: string,
    comment: string,
    hyperlink: string | null,
  ) => void
  onSelectCell: (selection: Selection) => void
  onAddParameter: (body: { label: string } & ParameterWrite) => void
  onUpdateParameter: (key: string, body: ParameterWrite) => void
  onDeleteParameter: (key: string) => void
  onDiscard: (parameterKey: string, columnKey: string) => void
}

function displayLabel(label: string, unit: string | null | undefined): string {
  const suffix = unit?.trim()
  if (!suffix) return label
  const tail = `, ${suffix}`
  if (label.endsWith(tail)) return label.slice(0, -tail.length).trim()
  return label
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
    const locked = cells.get(`${rows[row]}:${cols[col]}`)?.locked
    if (!locked) return { parameterKey: rows[row], columnKey: cols[col] }
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

export function TableTab({
  catalog,
  workbook,
  unsaved,
  history,
  busy,
  canWrite,
  onDraft,
  onConfirm,
  onSelectCell,
  onAddParameter,
  onUpdateParameter,
  onDeleteParameter,
  onDiscard,
}: Props) {
  const [selection, setSelection] = useState<Selection | null>(null)
  const [editValue, setEditValue] = useState('')
  const [link, setLink] = useState('')
  const [comment, setComment] = useState('')
  const [tableMode, setTableMode] = useState<'view' | 'edit'>('view')
  const [structureEdit, setStructureEdit] = useState(false)
  const [structKey, setStructKey] = useState('')
  const [structLabel, setStructLabel] = useState('')
  const [structUnit, setStructUnit] = useState('')
  const [structIndent, setStructIndent] = useState(1)
  const gridRef = useRef<HTMLDivElement | null>(null)
  const cells = useMemo(() => cellMap(workbook), [workbook])

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
  const editing = tableMode === 'edit' && canWrite
  const locked = Boolean(selectedCell?.locked) || !editing
  const readOnly = busy || locked

  function moveTo(key: string) {
    const next = nextCell(activeCatalog, cells, selection, key)
    if (!next) return
    if (
      editing &&
      selection &&
      !readOnly &&
      editValue !== (selectedCell?.display || '')
    ) {
      onDraft(selection.parameterKey, selection.columnKey, editValue, link || null)
    }
    setSelection(next)
    onSelectCell(next)
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

  return (
    <div className="tab-page">
      <div className="toolbar" data-guide="guide-colors">
        <div className="view-tabs" data-guide="guide-table-mode">
          <button
            type="button"
            className={tableMode === 'view' ? 'active' : ''}
            onClick={() => {
              setTableMode('view')
              setStructureEdit(false)
            }}
          >
            Режим просмотра
          </button>
          <button
            type="button"
            className={tableMode === 'edit' ? 'active' : ''}
            disabled={!canWrite}
            onClick={() => setTableMode('edit')}
          >
            Режим редактирования
          </button>
        </div>
        <span className="hint">
          {editing
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
      <div
        className="grid-wrap"
        data-guide="guide-sheet"
        ref={gridRef}
        tabIndex={0}
        onKeyDown={handleGridKey}
      >
        <table className={`sheet${structureEdit ? ' structure-edit' : ''}${editing ? ' edit-mode' : ' view-mode'}`}>
          <thead>
            <tr>
              <th className="param">Наименование параметра</th>
              <th className="unit">Ед. изм.</th>
              {activeCatalog.columns.map((col) => (
                <th key={col.key} className={selection?.columnKey === col.key ? 'col-hi' : ''}>
                  {col.label}
                </th>
              ))}
            </tr>
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
                  className={`param indent-${param.indent}${inRow ? ' row-hi' : ''}${structureEdit && structKey === param.key ? ' selected' : ''}`}
                  onClick={() => {
                    if (!structureEdit) return
                    setStructKey(param.key)
                    setStructLabel(displayLabel(param.label, param.unit))
                    setStructUnit(param.unit || '')
                    setStructIndent(param.indent)
                  }}
                >
                  {displayLabel(param.label, param.unit)}
                </th>
                <td className={`unit${inRow ? ' row-hi' : ''}`}>
                  {param.row_kind === 'editable' ? param.unit || '' : ''}
                </td>
                {activeCatalog.columns.map((col) => {
                  const inCol = selection?.columnKey === col.key
                  const axis = `${inRow ? ' row-hi' : ''}${inCol ? ' col-hi' : ''}`
                  if (param.row_kind !== 'editable') {
                    return <td key={col.key} className={`computed${axis}`} />
                  }
                  const cell = cells.get(`${param.key}:${col.key}`)
                  const selected = inRow && inCol
                  const cellLocked = Boolean(cell?.locked) || !editing || busy
                  const status = cell?.locked ? 'computed' : cell?.status || 'empty'
                  const cellOptions = (param.options && param.options.length > 0
                    ? param.options
                    : cell?.options) || []
                  return (
                    <td
                      key={col.key}
                      className={`value ${status}${selected ? ' selected' : ''}${axis}`}
                      onClick={() => {
                        const next = { parameterKey: param.key, columnKey: col.key }
                        setSelection(next)
                        onSelectCell(next)
                        if (!editing) gridRef.current?.focus()
                      }}
                    >
                      {selected && editing && !cellLocked ? (
                        cellOptions.length > 0 ? (
                          <CellDictSelect
                            key={`${param.key}:${col.key}`}
                            value={editValue}
                            options={cellOptions}
                            onPick={(next) => {
                              setEditValue(next)
                              onDraft(param.key, col.key, next, link || null)
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
                              if (editValue !== (cell?.display || '')) {
                                onDraft(param.key, col.key, editValue, link || null)
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
                              {cell.display || ''}
                            </a>
                          ) : (
                            cell?.display || '\u00a0'
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
      <div className="side" data-guide="guide-edit">
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
                      onBlur={() => onDraft(selection.parameterKey, selection.columnKey, editValue, link || null)}
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
              {selectedCell?.locked ? (
                <div className="hint">Поле заблокировано правилом (венцовая диафрагма / унификация).</div>
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
      </div>
    </div>
  )
}
