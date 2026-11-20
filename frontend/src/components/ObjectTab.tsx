import { useMemo, useRef, useState } from 'react'
import type { ObjectItem, Workbook } from '../types'

type NewObject = {
  factory_number: string
  turbine_name: string
  station_name: string
  station_number: string
  series_turbines: string
  kind: string
}

type Props = {
  objects: ObjectItem[]
  selectedId: string
  workbook: Workbook | null
  busy: boolean
  message: string
  onSelect: (objectId: string) => void
  onCreate: (payload: NewObject) => void
  onImportObjectParameters: (file: File) => void
  onImportTriangle: (file: File) => void
  canWrite: boolean
}

const emptyObject: NewObject = {
  factory_number: '',
  turbine_name: '',
  station_name: '',
  station_number: '',
  series_turbines: '',
  kind: '',
}

export function ObjectTab({
  objects,
  selectedId,
  workbook,
  busy,
  message,
  onSelect,
  onCreate,
  onImportObjectParameters,
  onImportTriangle,
  canWrite,
}: Props) {
  const objectParametersRef = useRef<HTMLInputElement>(null)
  const triangleRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [draft, setDraft] = useState<NewObject>(emptyObject)
  const selected = objects.find((item) => item.id === selectedId)
  const suggestions = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('ru')
    if (!query || !suggestionsOpen) return []
    return objects
      .filter((item) => item.name.toLocaleLowerCase('ru').includes(query))
      .slice(0, 30)
  }, [objects, search, suggestionsOpen])
  const createEnabled = Object.values(draft).every((value) => value.trim())

  function updateDraft(field: keyof NewObject, value: string) {
    setDraft((current) => ({ ...current, [field]: value }))
  }

  return (
    <div className="tab-page">
      <div className="toolbar">
        <label className="object-search" data-guide="guide-object">
          Объект
          <input
            type="search"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={suggestions.length > 0}
            aria-controls="object-suggestions"
            placeholder="Начните вводить название объекта"
            value={search}
            disabled={busy}
            onFocus={() => setSuggestionsOpen(true)}
            onChange={(event) => {
              setSearch(event.target.value)
              setSuggestionsOpen(true)
              if (selectedId) onSelect('')
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setSuggestionsOpen(false)
            }}
          />
          {suggestions.length > 0 ? (
            <div className="object-suggestions" id="object-suggestions" role="listbox">
              {suggestions.map((item) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={item.id === selectedId}
                  key={item.id}
                  disabled={busy}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setSearch(item.name)
                    setSuggestionsOpen(false)
                    onSelect(item.id)
                  }}
                >
                  {item.name}{item.has_workbook ? ' (есть сводка)' : ''}
                </button>
              ))}
            </div>
          ) : null}
        </label>
      </div>

      {selected?.has_workbook ? (
        <div className="warn">По этому объекту работа уже начата. Открыта существующая сводка.</div>
      ) : null}
      {message ? <div className="ok">{message}</div> : null}

      {selected ? (
        <div className="hint">
          Станция: {selected.station || '—'}; турбина: {selected.turbine || '—'}; ID_projects:{' '}
          {selected.external_id || '—'}
        </div>
      ) : (
        <div className="hint">Без выбранного объекта таблица ИД и отчёт недоступны.</div>
      )}

      <div className="toolbar">
        <button
          type="button"
          className="win-btn"
          disabled={!workbook || busy || !canWrite}
          onClick={() => objectParametersRef.current?.click()}
        >
          Импортировать параметры объекта из Excel
        </button>
        <input
          ref={objectParametersRef}
          type="file"
          accept=".xlsx"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onImportObjectParameters(file)
            event.target.value = ''
          }}
        />
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
      </div>

      <h3 style={{ margin: '8px 0 0' }}>Создать объект</h3>
      <div className="form-grid">
        <span>Наименование станции</span>
        <input value={draft.station_name} onChange={(event) => updateDraft('station_name', event.target.value)} />
        <span>Номер станции</span>
        <input value={draft.station_number} onChange={(event) => updateDraft('station_number', event.target.value)} />
        <span>Наименование турбины</span>
        <input value={draft.turbine_name} onChange={(event) => updateDraft('turbine_name', event.target.value)} />
        <span>Заводской номер</span>
        <input value={draft.factory_number} onChange={(event) => updateDraft('factory_number', event.target.value)} />
        <span>Серия турбин</span>
        <input value={draft.series_turbines} onChange={(event) => updateDraft('series_turbines', event.target.value)} />
        <span>Тип объекта (kind)</span>
        <input value={draft.kind} onChange={(event) => updateDraft('kind', event.target.value)} />
      </div>
      <div>
        <button
          type="button"
          className="win-btn"
          disabled={!createEnabled || busy || !canWrite}
          onClick={() => {
            onCreate(draft)
            setDraft(emptyObject)
          }}
        >
          Создать объект
        </button>
      </div>
    </div>
  )
}
