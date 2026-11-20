import { useEffect, useState } from 'react'
import type { Catalog, Workbook, WorkbookSheet } from '../types'

type IdTableData = {
  sheetId: string
  catalog: Catalog
  workbook: Workbook
}

type Props = {
  workbook: Workbook | null
  sheets: WorkbookSheet[]
  idTableData: IdTableData | null
  busy: boolean
  onPreview: (sheetId: string, type: string) => void
  onExportWord: (sheetId: string, parameterKeys: string[], columnKeys: string[], tableNumber: number) => void
}

export function ReportTab({ workbook, sheets, idTableData, busy, onPreview, onExportWord }: Props) {
  const [type, setType] = useState('short')
  const [sheetId, setSheetId] = useState(workbook?.id || '')
  const [selectedParameterKeys, setSelectedParameterKeys] = useState<Set<string>>(new Set())
  const [selectedColumnKeys, setSelectedColumnKeys] = useState<Set<string>>(new Set())
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => {
    if (!workbook) {
      setSheetId('')
      return
    }
    setSheetId(workbook.id)
    onPreview(workbook.id, type)
  }, [workbook?.id])

  useEffect(() => {
    if (idTableData?.sheetId !== sheetId) return
    const parameterKeys = new Set(
      idTableData.catalog.parameters.filter((parameter) => parameter.row_kind !== 'section').map((parameter) => parameter.key),
    )
    const columnKeys = new Set(idTableData.catalog.columns.map((column) => column.key))
    const greenCells = idTableData.workbook.cells.filter(
      (cell) => cell.status === 'confirmed' && parameterKeys.has(cell.parameter_key) && columnKeys.has(cell.column_key),
    )
    setSelectedParameterKeys(new Set(greenCells.map((cell) => cell.parameter_key)))
    setSelectedColumnKeys(new Set(greenCells.map((cell) => cell.column_key)))
    setShowPreview(false)
  }, [idTableData, sheetId])

  if (!workbook) return null

  const tableData = idTableData?.sheetId === sheetId ? idTableData : null
  const idTableCells = new Map(
    tableData?.workbook.cells.map((cell) => [`${cell.parameter_key}:${cell.column_key}`, cell]) || [],
  )
  const selectableParameters = tableData?.catalog.parameters.filter((parameter) => parameter.row_kind !== 'section') || []
  const selectedGroups = new Set(
    selectableParameters.filter((parameter) => selectedParameterKeys.has(parameter.key)).map((parameter) => parameter.group),
  )
  const previewParameters = tableData?.catalog.parameters.filter((parameter) =>
    parameter.row_kind === 'section' ? selectedGroups.has(parameter.key) : selectedParameterKeys.has(parameter.key),
  ) || []
  const toggleParameter = (parameterKey: string) => {
    setSelectedParameterKeys((current) => {
      const next = new Set(current)
      if (next.has(parameterKey)) next.delete(parameterKey)
      else next.add(parameterKey)
      return next
    })
    setShowPreview(false)
  }
  const toggleColumn = (columnKey: string) => {
    setSelectedColumnKeys((current) => {
      const next = new Set(current)
      if (next.has(columnKey)) next.delete(columnKey)
      else next.add(columnKey)
      return next
    })
    setShowPreview(false)
  }

  return (
    <div className="tab-page report-page">
      <div className="report-toolbar">
        <label>Тип записки
          <select value={type} disabled={busy} onChange={(event) => setType(event.target.value)}>
            <option value="short">Исходные данные по проточной части</option>
            <option value="full">Исходные данные по облопачиванию</option>
          </select>
        </label>
        <label>Лист таблицы ИД
          <select value={sheetId} disabled={busy} onChange={(event) => {
            const nextSheetId = event.target.value
            setSheetId(nextSheetId)
            onPreview(nextSheetId, type)
          }}>
            {sheets.map((sheet) => <option key={sheet.id} value={sheet.id}>{sheet.name}</option>)}
          </select>
        </label>
      </div>

      {tableData ? (
        <>
          <div className="grid-wrap report-id-grid">
            <table className="sheet view-mode report-selectable-table">
              <thead>
                <tr>
                  <th className="report-row-toggle-header" rowSpan={3} />
                  <th className="param" rowSpan={3}>Наименование параметра</th>
                  <th className="unit" rowSpan={3}>Ед. изм.</th>
                  {tableData.catalog.columns.length > 0 ? (
                    <th className="step-group" colSpan={tableData.catalog.columns.length}>Ступени</th>
                  ) : null}
                </tr>
                <tr>
                  {tableData.catalog.columns.map((column) => {
                    const included = selectedColumnKeys.has(column.key)
                    return (
                      <th className="report-column-toggle" key={column.key}>
                        <button
                          type="button"
                          className={`report-toggle-button ${included ? 'included' : 'excluded'}`}
                          aria-pressed={included}
                          aria-label={`${included ? 'Убрать' : 'Добавить'} столбец ${column.label}`}
                          title={`${included ? 'Убрать из отчёта' : 'Добавить в отчёт'}: ${column.label}`}
                          onClick={() => toggleColumn(column.key)}
                        >{included ? '+' : '−'}</button>
                      </th>
                    )
                  })}
                </tr>
                <tr>
                  {tableData.catalog.columns.map((column) => <th key={column.key}>{column.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {tableData.catalog.parameters.map((parameter) => {
                  const included = selectedParameterKeys.has(parameter.key)
                  const label = parameter.unit && parameter.label.endsWith(`, ${parameter.unit}`)
                    ? parameter.label.slice(0, -parameter.unit.length - 2).trim()
                    : parameter.label
                  return (
                    <tr
                      key={parameter.key}
                      className={parameter.row_kind === 'section' || parameter.row_kind === 'computed' ? 'section' : ''}
                    >
                      <td className="report-row-toggle-cell">
                        {parameter.row_kind !== 'section' ? (
                          <button
                            type="button"
                            className={`report-toggle-button ${included ? 'included' : 'excluded'}`}
                            aria-pressed={included}
                            aria-label={`${included ? 'Убрать' : 'Добавить'} строку ${label}`}
                            title={`${included ? 'Убрать из отчёта' : 'Добавить в отчёт'}: ${label}`}
                            onClick={() => toggleParameter(parameter.key)}
                          >{included ? '+' : '−'}</button>
                        ) : null}
                      </td>
                      <th className={`param indent-${parameter.indent}`}>{label}</th>
                      <td className="unit">{parameter.row_kind === 'editable' ? parameter.unit : ''}</td>
                      {tableData.catalog.columns.map((column) => {
                        if (parameter.row_kind !== 'editable') return <td key={column.key} className="computed" />
                        const cell = idTableCells.get(`${parameter.key}:${column.key}`)
                        const status = cell?.locked ? 'computed' : cell?.status || 'empty'
                        return (
                          <td key={column.key} className={`value ${status}${cell?.unified ? ' unified' : ''}`}>
                            <span className="cell-text">{cell?.display || '\u00a0'}</span>
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="report-preview-button-row">
            <button
              type="button"
              className="win-btn report-preview-button"
              disabled={selectedParameterKeys.size === 0 || selectedColumnKeys.size === 0}
              onClick={() => setShowPreview(true)}
            >Предпросмотр</button>
            <button
              type="button"
              className="win-btn report-preview-button"
              disabled={busy || selectedParameterKeys.size === 0 || selectedColumnKeys.size === 0}
              onClick={() => onExportWord(sheetId, [...selectedParameterKeys], [...selectedColumnKeys], 1)}
            >Экспорт в Word</button>
          </div>
          {showPreview ? (
            <div className="modal-back report-preview-back" onClick={() => setShowPreview(false)}>
              <section
                className="modal report-preview-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="report-preview-title"
                onClick={(event) => event.stopPropagation()}
              >
                <h2 id="report-preview-title">Предпросмотр таблицы</h2>
                <div className="report-preview-body">
                  <div className="grid-wrap report-preview-grid">
                    <table className="sheet view-mode">
                      <thead>
                        <tr>
                          <th className="param" rowSpan={2}>Наименование параметра</th>
                          <th className="unit" rowSpan={2}>Ед. изм.</th>
                          {selectedColumnKeys.size > 0 ? <th className="step-group" colSpan={selectedColumnKeys.size}>Ступени</th> : null}
                        </tr>
                        <tr>{tableData.catalog.columns.filter((column) => selectedColumnKeys.has(column.key)).map((column) => <th key={column.key}>{column.label}</th>)}</tr>
                      </thead>
                      <tbody>
                        {previewParameters.map((parameter) => (
                          <tr
                            key={parameter.key}
                            className={parameter.row_kind === 'section' || parameter.row_kind === 'computed' ? 'section' : ''}
                          >
                            <th className={`param indent-${parameter.indent}`}>
                              {parameter.unit && parameter.label.endsWith(`, ${parameter.unit}`)
                                ? parameter.label.slice(0, -parameter.unit.length - 2).trim()
                                : parameter.label}
                            </th>
                            <td className="unit">{parameter.row_kind === 'editable' ? parameter.unit : ''}</td>
                            {tableData.catalog.columns.filter((column) => selectedColumnKeys.has(column.key)).map((column) => {
                              if (parameter.row_kind !== 'editable') return <td key={column.key} className="computed" />
                              const cell = idTableCells.get(`${parameter.key}:${column.key}`)
                              const status = cell?.locked ? 'computed' : cell?.status || 'empty'
                              return (
                                <td key={column.key} className={`value ${status}${cell?.unified ? ' unified' : ''}`}>
                                  <span className="cell-text">{cell?.display || '\u00a0'}</span>
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="report-preview-actions">
                  <button type="button" className="win-btn" onClick={() => setShowPreview(false)}>Закрыть</button>
                </div>
              </section>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
