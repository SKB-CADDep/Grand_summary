import { useMemo, useState } from 'react'
import type { ChangelogRelease } from '../types'

type Props = {
  releases: ChangelogRelease[]
}

export function ChangelogViewer({ releases }: Props) {
  const [query, setQuery] = useState('')
  const [groupBy, setGroupBy] = useState<'date' | 'action'>('date')
  const [selected, setSelected] = useState<string>(releases[0]?.version || '')

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return releases
    return releases.filter((item) => {
      const blob = `${item.version} ${item.date} ${item.title} ${item.items.join(' ')}`.toLowerCase()
      return blob.includes(needle)
    })
  }, [releases, query])

  const groups = useMemo(() => {
    const map = new Map<string, ChangelogRelease[]>()
    for (const item of filtered) {
      const key = groupBy === 'date' ? item.date : item.title
      const list = map.get(key) || []
      list.push(item)
      map.set(key, list)
    }
    return [...map.entries()]
  }, [filtered, groupBy])

  const current = filtered.find((item) => item.version === selected) || filtered[0]

  return (
    <div className="changelog-view">
      <div className="toolbar">
        <input
          type="text"
          placeholder="Фильтр по версии, дате или тексту…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <label>
          Группировка
          <select value={groupBy} onChange={(event) => setGroupBy(event.target.value as 'date' | 'action')}>
            <option value="date">По дате</option>
            <option value="action">По действиям</option>
          </select>
        </label>
      </div>
      <div className="changelog-split">
        <ul className="changelog-tree">
          {groups.map(([key, items]) => (
            <li key={key}>
              <div className="changelog-group">{key}</div>
              {items.map((item) => (
                <button
                  type="button"
                  key={item.version}
                  className={current?.version === item.version ? 'active' : ''}
                  onClick={() => setSelected(item.version)}
                >
                  {groupBy === 'date' ? `v${item.version}` : `v${item.version} — ${item.date}`}
                </button>
              ))}
            </li>
          ))}
        </ul>
        <div className="changelog-body">
          {current ? (
            <>
              <h3>
                v{current.version} {current.date}
              </h3>
              <p>
                <strong>{current.title}</strong>
              </p>
              <ul>
                {current.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : (
            <p>Нет записей</p>
          )}
        </div>
      </div>
    </div>
  )
}
