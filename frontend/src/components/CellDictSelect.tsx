import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  value: string
  options: string[]
  onPick: (value: string) => void
  onNavigate: (key: string) => void
}

export function CellDictSelect({ value, options, onPick, onNavigate }: Props) {
  const hostRef = useRef<HTMLButtonElement | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)
  const [open, setOpen] = useState(true)
  const [box, setBox] = useState<DOMRect | null>(null)
  const [query, setQuery] = useState('')
  const items = useMemo(() => {
    const unique = ['', ...options]
    if (value && !unique.includes(value)) unique.push(value)
    return unique
  }, [options, value])
  const filteredItems = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return needle
      ? items.filter((item) => item.toLocaleLowerCase().includes(needle))
      : items
  }, [items, query])
  const current = Math.max(
    0,
    items.findIndex((item) => item === value),
  )
  const [active, setActive] = useState(current)

  useEffect(() => {
    setActive(query ? 0 : current)
  }, [query, current])

  function place() {
    setBox(hostRef.current?.getBoundingClientRect() ?? null)
  }

  useLayoutEffect(() => {
    place()
    setOpen(true)
  }, [])

  useEffect(() => {
    if (open && box) searchRef.current?.focus()
  }, [open, box])

  useEffect(() => {
    let armed = false
    const timer = window.setTimeout(() => {
      armed = true
    }, 80)

    const onDoc = (event: MouseEvent) => {
      const target = event.target as Node | null
      if (hostRef.current?.contains(target) || listRef.current?.contains(target)) return
      setOpen(false)
    }
    const onScroll = (event: Event) => {
      if (!armed) return
      if (listRef.current && event.target instanceof Node && listRef.current.contains(event.target)) return
      setOpen(false)
    }

    document.addEventListener('mousedown', onDoc)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  function pick(item: string) {
    onPick(item)
    setOpen(false)
    hostRef.current?.focus()
  }

  function onKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight' || event.key === 'Tab') {
      event.preventDefault()
      event.stopPropagation()
      onNavigate(event.key === 'Tab' && event.shiftKey ? 'ShiftTab' : event.key)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      event.stopPropagation()
      if (open) pick(filteredItems[active] ?? filteredItems[0] ?? '')
      else {
        setQuery('')
        place()
        setOpen(true)
        requestAnimationFrame(() => searchRef.current?.focus())
      }
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      event.stopPropagation()
      if (!open) {
        setQuery('')
        place()
        setOpen(true)
        requestAnimationFrame(() => searchRef.current?.focus())
        return
      }
      if (!filteredItems.length) return
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActive((index) => (index + delta + filteredItems.length) % filteredItems.length)
    }
  }

  function onSearchKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Tab') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      onNavigate(event.shiftKey ? 'ShiftTab' : 'Tab')
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      hostRef.current?.focus()
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      event.stopPropagation()
      if (filteredItems.length) pick(filteredItems[active] ?? '')
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      event.stopPropagation()
      if (!filteredItems.length) return
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActive((index) => (index + delta + filteredItems.length) % filteredItems.length)
    }
  }

  const listStyle = (() => {
    if (!box) return undefined
    const maxHeight = 240
    const gap = 1
    const spaceBelow = window.innerHeight - box.bottom - 8
    const openUp = spaceBelow < 120 && box.top > spaceBelow
    return {
      top: openUp ? undefined : box.bottom + gap,
      bottom: openUp ? window.innerHeight - box.top + gap : undefined,
      left: box.left,
      minWidth: Math.max(box.width, 180),
      maxHeight,
    }
  })()

  return (
    <>
      <button
        ref={hostRef}
        type="button"
        className="cell-edit cell-dict-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation()
          if (open) {
            setOpen(false)
            return
          }
          setQuery('')
          place()
          setOpen(true)
          requestAnimationFrame(() => searchRef.current?.focus())
        }}
        onKeyDown={onKey}
      >
        <span>{value || '—'}</span>
        <span className="cell-dict-mark">▾</span>
      </button>
      {open && box
        ? createPortal(
            <ul
              ref={listRef}
              className="cell-dict-list"
              role="listbox"
              style={listStyle}
              onWheel={(event) => event.stopPropagation()}
            >
              <li className="cell-dict-search" role="presentation">
                <input
                  ref={searchRef}
                  type="search"
                  aria-label="Поиск по списку"
                  placeholder="Поиск…"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={onSearchKey}
                  onClick={(event) => event.stopPropagation()}
                />
              </li>
              {filteredItems.length ? filteredItems.map((item, index) => (
                <li
                  key={`${index}:${item || 'empty'}`}
                  className={index === active ? 'active' : ''}
                  role="option"
                  aria-selected={item === value}
                  onClick={(event) => {
                    event.stopPropagation()
                    pick(item)
                  }}
                >
                  {item || '—'}
                </li>
              )) : (
                <li className="cell-dict-empty" role="presentation">Варианты не найдены</li>
              )}
            </ul>,
            document.body,
          )
        : null}
    </>
  )
}
