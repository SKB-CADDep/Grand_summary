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
  const listRef = useRef<HTMLUListElement | null>(null)
  const [open, setOpen] = useState(true)
  const [box, setBox] = useState<DOMRect | null>(null)
  const items = useMemo(() => {
    const unique = ['', ...options]
    if (value && !unique.includes(value)) unique.push(value)
    return unique
  }, [options, value])
  const current = Math.max(
    0,
    items.findIndex((item) => item === value),
  )
  const [active, setActive] = useState(current)

  function place() {
    setBox(hostRef.current?.getBoundingClientRect() ?? null)
  }

  useLayoutEffect(() => {
    place()
    setOpen(true)
    hostRef.current?.focus()
  }, [])

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
      if (open) pick(items[active] ?? '')
      else {
        place()
        setOpen(true)
      }
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      event.stopPropagation()
      if (!open) {
        place()
        setOpen(true)
        return
      }
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActive((index) => (index + delta + items.length) % items.length)
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
          place()
          setOpen((prev) => !prev)
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
              onMouseDown={(event) => event.preventDefault()}
              onWheel={(event) => event.stopPropagation()}
            >
              {items.map((item, index) => (
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
              ))}
            </ul>,
            document.body,
          )
        : null}
    </>
  )
}
