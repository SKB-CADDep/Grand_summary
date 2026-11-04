import { useMemo, useState } from 'react'
import type { JournalItem } from '../types'

type Props = {
  items: JournalItem[]
}

const ACTION_FILTERS = [
  { id: '', label: 'Все' },
  { id: 'confirmed', label: 'Ячейки' },
  { id: 'parameter', label: 'Параметры' },
  { id: 'imported', label: 'Импорт' },
  { id: 'version', label: 'Версии' },
  { id: 'report', label: 'Сводки' },
]

export function UserJournal({ items }: Props) {
  const [view, setView] = useState<'table' | 'feed'>('table')
  const [query, setQuery] = useState('')
  const [field, setField] = useState('any')
  const [kind, setKind] = useState('')

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return items.filter((item) => {
      if (kind === 'parameter' && !item.action.startsWith('parameter')) return false
      if (kind && kind !== 'parameter' && item.action !== kind) return false
      if (!needle) return true
      const map: Record<string, string> = {
        any: `${item.actor} ${item.object_name} ${item.action_label} ${item.summary} ${item.comment}`,
        actor: item.actor,
        object: item.object_name,
        action: item.action_label,
        comment: item.comment,
        summary: item.summary,
      }
      return (map[field] || map.any).toLowerCase().includes(needle)
    })
  }, [items, query, field, kind])

  return (
    <div>
      <div className="toolbar">
        <label>
          Показать
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            {ACTION_FILTERS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Поле
          <select value={field} onChange={(event) => setField(event.target.value)}>
            <option value="any">Любое поле</option>
            <option value="actor">Кто</option>
            <option value="object">Объект</option>
            <option value="action">Действие</option>
            <option value="comment">Комментарий</option>
            <option value="summary">Изменения</option>
          </select>
        </label>
        <input
          type="text"
          placeholder="Фильтр…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="view-tabs">
        <button type="button" className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>
          Таблица
        </button>
        <button type="button" className={view === 'feed' ? 'active' : ''} onClick={() => setView('feed')}>
          Лента
        </button>
      </div>
      {view === 'table' ? (
        <table className="history">
          <thead>
            <tr>
              <th>Время</th>
              <th>Кто</th>
              <th>Объект</th>
              <th>Действие</th>
              <th>Изменения</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5}>Записей нет</td>
              </tr>
            ) : (
              filtered.map((item) => (
                <tr key={item.id}>
                  <td>{new Date(item.created_at).toLocaleString()}</td>
                  <td>{item.actor}</td>
                  <td>{item.object_name}</td>
                  <td>{item.action_label}</td>
                  <td>
                    {item.summary}
                    {item.comment ? ` · ${item.comment}` : ''}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      ) : (
        <ul className="journal-feed">
          {filtered.length === 0 ? <li className="hint">Записей нет</li> : null}
          {filtered.map((item) => (
            <li key={item.id} className="journal-card">
              <strong>
                {item.action_label}
                {item.object_name ? ` · ${item.object_name}` : ''}
              </strong>
              <div className="hint">
                {item.actor} · {new Date(item.created_at).toLocaleString()}
              </div>
              {item.old_value || item.new_value ? (
                <div className="journal-diff">
                  {item.old_value ? <div className="diff-old">− {item.old_value}</div> : null}
                  {item.new_value ? <div className="diff-new">+ {item.new_value}</div> : null}
                </div>
              ) : (
                <div>{item.summary}</div>
              )}
              {item.comment ? <div className="hint">{item.comment}</div> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
