import { useState } from 'react'
import type { PreviewTable, VersionItem, Workbook } from '../types'

type Props = {
  workbook: Workbook | null
  versions: VersionItem[]
  tables: PreviewTable[]
  busy: boolean
  onPreview: (type: string, versionId: string) => void
  onCreate: (type: string, versionId: string, notes: string) => void
  onRestore: (versionId: string) => void
  onIssue: (description: string) => void
  canWrite: boolean
}

export function ReportTab({
  workbook,
  versions,
  tables,
  busy,
  onPreview,
  onCreate,
  onRestore,
  onIssue,
  canWrite,
}: Props) {
  const [type, setType] = useState('short')
  const [versionId, setVersionId] = useState('')
  const [notes, setNotes] = useState('')
  const [issueText, setIssueText] = useState('Выдано в другие отделы')

  if (!workbook) {
    return (
      <div className="tab-page">
        <div className="hint">Сначала выберите объект на вкладке «Объект и треугольники».</div>
      </div>
    )
  }

  return (
    <div className="tab-page">
      <div className="toolbar">
        <label data-guide="guide-report-type">
          Тип
          <select value={type} onChange={(event) => setType(event.target.value)}>
            <option value="short">Короткая служебка</option>
            <option value="full">Полная сводка</option>
          </select>
        </label>
        <label>
          Сравнить с версией
          <select value={versionId} onChange={(event) => setVersionId(event.target.value)}>
            <option value="">без сравнения</option>
            {versions.map((item) => (
              <option key={item.id} value={item.id}>
                {new Date(item.created_at).toLocaleString()} · {item.kind} · {item.description}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="win-btn" disabled={busy} onClick={() => onPreview(type, versionId)}>
          Обновить превью
        </button>
        <button
          type="button"
          className="win-btn"
          data-guide="guide-report-create"
          disabled={busy || !canWrite}
          onClick={() => onCreate(type, versionId, notes)}
        >
          Создать сводку
        </button>
      </div>
      <div className="toolbar">
        <input
          type="text"
          value={issueText}
          onChange={(event) => setIssueText(event.target.value)}
          style={{ minWidth: 240 }}
        />
        <button
          type="button"
          className="win-btn"
          disabled={busy || !canWrite}
          onClick={() => onIssue(issueText)}
        >
          Зафиксировать как выданную
        </button>
        <button
          type="button"
          className="win-btn"
          disabled={busy || !canWrite || !versionId}
          onClick={() => onRestore(versionId)}
        >
          Загрузить выбранную версию
        </button>
      </div>
      <textarea
        placeholder="Дополнительный лист / примечания в Word (не комментарии ячеек)"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />
      <div className="hint">
        Жёлтые ячейки в отчёте — изменения относительно выбранной версии. Комментарии в Word не попадают.
      </div>
      <div className="grid-wrap">
        {tables.map((table) => (
          <div key={table.title}>
            <h3>{table.title}</h3>
            <table className="preview-table">
              <thead>
                <tr>
                  <th>Наименование параметра</th>
                  {table.columns.map((col) => (
                    <th key={col.key}>{col.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row) => (
                  <tr key={row.parameter_key}>
                    <td>{row.label}</td>
                    {row.cells.map((cell) => (
                      <td
                        key={cell.column_key}
                        style={cell.fill ? { background: `#${cell.fill}` } : undefined}
                      >
                        {cell.value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  )
}
