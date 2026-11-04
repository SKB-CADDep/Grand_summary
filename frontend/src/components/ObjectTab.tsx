import { useRef, useState } from 'react'
import type { ObjectItem, Workbook } from '../types'

type Props = {
  objects: ObjectItem[]
  selectedId: string
  workbook: Workbook | null
  busy: boolean
  message: string
  onSelect: (objectId: string) => void
  onCreate: (payload: { name: string; station: string; turbine: string; cylinder: string; external_id: string }) => void
  onImportObjects: (file: File) => void
  onImportTriangle: (file: File) => void
  onAddStage: (label: string) => void
  onSyncObjects: () => void
  canWrite: boolean
}

export function ObjectTab({
  objects,
  selectedId,
  workbook,
  busy,
  message,
  onSelect,
  onCreate,
  onImportObjects,
  onImportTriangle,
  onAddStage,
  onSyncObjects,
  canWrite,
}: Props) {
  const triangleRef = useRef<HTMLInputElement>(null)
  const objectsRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [station, setStation] = useState('')
  const [turbine, setTurbine] = useState('')
  const [cylinder, setCylinder] = useState('ЦСД')
  const [externalId, setExternalId] = useState('')
  const [stageLabel, setStageLabel] = useState('')
  const selected = objects.find((item) => item.id === selectedId)

  return (
    <div className="tab-page">
      <div className="toolbar">
        <label data-guide="guide-object">
          Объект
          <select
            value={selectedId}
            onChange={(event) => onSelect(event.target.value)}
            disabled={busy}
          >
            <option value="">— выберите объект —</option>
            {objects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
                {item.has_workbook ? ' (есть сводка)' : ''}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="win-btn"
          onClick={() => objectsRef.current?.click()}
          disabled={busy || !canWrite}
        >
          Загрузить объекты из Excel
        </button>
        <button
          type="button"
          className="win-btn"
          data-guide="guide-sync"
          onClick={onSyncObjects}
          disabled={busy || !canWrite}
        >
          Синхронизировать объекты
        </button>
        <input
          ref={objectsRef}
          type="file"
          accept=".xlsx,.xlsm"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onImportObjects(file)
            event.target.value = ''
          }}
        />
      </div>

      {selected?.has_workbook ? (
        <div className="warn">По этому объекту работа уже начата. Открыта существующая сводка.</div>
      ) : null}
      {message ? <div className="ok">{message}</div> : null}

      {selected ? (
        <div className="hint">
          Станция: {selected.station || '—'}; турбина: {selected.turbine || '—'}; цилиндр:{' '}
          {selected.cylinder || '—'}; ID: {selected.external_id || '—'}
        </div>
      ) : (
        <div className="hint">Без выбранного объекта таблица ИД и отчёт недоступны.</div>
      )}

      <div className="toolbar">
        <button
          type="button"
          className="win-btn"
          data-guide="guide-triangle"
          disabled={!workbook || busy || !canWrite}
          onClick={() => triangleRef.current?.click()}
        >
          Импортировать из Excel (треугольники)
        </button>
        <input
          ref={triangleRef}
          type="file"
          accept=".xlsx,.xlsm"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onImportTriangle(file)
            event.target.value = ''
          }}
        />
        <input
          type="text"
          placeholder="Новая ступень"
          value={stageLabel}
          onChange={(event) => setStageLabel(event.target.value)}
        />
        <button
          type="button"
          className="win-btn"
          disabled={!workbook || !stageLabel.trim() || busy || !canWrite}
          onClick={() => {
            onAddStage(stageLabel)
            setStageLabel('')
          }}
        >
          Добавить ступень
        </button>
      </div>

      <h3 style={{ margin: '8px 0 0' }}>Создать объект, если его нет в списке</h3>
      <div className="form-grid">
        <span>Наименование</span>
        <input value={name} onChange={(event) => setName(event.target.value)} />
        <span>Станция</span>
        <input value={station} onChange={(event) => setStation(event.target.value)} />
        <span>Турбина</span>
        <input value={turbine} onChange={(event) => setTurbine(event.target.value)} />
        <span>Цилиндр</span>
        <input value={cylinder} onChange={(event) => setCylinder(event.target.value)} />
        <span>external_id</span>
        <input value={externalId} onChange={(event) => setExternalId(event.target.value)} />
      </div>
      <div>
        <button
          type="button"
          className="win-btn"
          disabled={!name.trim() || busy || !canWrite}
          onClick={() =>
            onCreate({
              name: name.trim(),
              station,
              turbine,
              cylinder,
              external_id: externalId,
            })
          }
        >
          Создать объект
        </button>
      </div>
    </div>
  )
}
