import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from './api'
import { ChangelogViewer } from './components/ChangelogViewer'
import { Dialog } from './components/Dialog'
import { GuideChoice, GuideOverlay } from './components/Guide'
import { ObjectTab } from './components/ObjectTab'
import { ReportTab } from './components/ReportTab'
import { TableTab } from './components/TableTab'
import { UserJournal } from './components/UserJournal'
import { GUIDE_SEEN_KEY, tourSteps, type GuideKind } from './guide'
import { clearKeys, makeEntry, pushEntry, takeSnap, type HistoryEntry } from './sessionHistory'
import type {
  Catalog,
  CellChange,
  ChangelogRelease,
  JournalItem,
  NotificationItem,
  ObjectItem,
  PreviewTable,
  TabId,
  UnsavedCell,
  VersionItem,
  Workbook,
} from './types'

type HelpKind = 'instruction' | 'about' | 'changelog' | 'unsaved' | 'notes' | 'user-journal' | null

function expectedAt(workbook: Workbook | null, parameterKey: string, columnKey: string) {
  const cell = workbook?.cells.find(
    (item) => item.parameter_key === parameterKey && item.column_key === columnKey,
  )
  return cell?.updated_at ?? null
}

export default function App() {
  const [username, setUsername] = useState('')
  const [canWrite, setCanWrite] = useState(true)
  const [objects, setObjects] = useState<ObjectItem[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [workbook, setWorkbook] = useState<Workbook | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [tab, setTab] = useState<TabId>('object')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [menuOpen, setMenuOpen] = useState<'file' | 'help' | 'notes' | null>(null)
  const [help, setHelp] = useState<HelpKind>(null)
  const [helpText, setHelpText] = useState('')
  const [history, setHistory] = useState<CellChange[]>([])
  const [unsaved, setUnsaved] = useState<UnsavedCell[]>([])
  const [versions, setVersions] = useState<VersionItem[]>([])
  const [tables, setTables] = useState<PreviewTable[]>([])
  const [pendingTab, setPendingTab] = useState<TabId | null>(null)
  const [unsavedComments, setUnsavedComments] = useState<Record<string, string>>({})
  const [notes, setNotes] = useState<NotificationItem[]>([])
  const [changelogReleases, setChangelogReleases] = useState<ChangelogRelease[]>([])
  const [journalItems, setJournalItems] = useState<JournalItem[]>([])
  const [guideOffer, setGuideOffer] = useState(false)
  const [guideKind, setGuideKind] = useState<GuideKind | null>(null)
  const [guideIndex, setGuideIndex] = useState(0)
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([])
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([])
  const historyBusy = useRef(false)
  const workbookIdRef = useRef<string | null>(null)

  const refreshUnsaved = useCallback(async (workbookId: string) => {
    setUnsaved(await api.unsaved(workbookId))
  }, [])

  const reloadWorkbook = useCallback(async (workbookId: string) => {
    const [next, nextCatalog, nextUnsaved] = await Promise.all([
      api.workbook(workbookId),
      api.catalog(workbookId),
      api.unsaved(workbookId),
    ])
    setWorkbook(next)
    setCatalog(nextCatalog)
    setUnsaved(nextUnsaved)
  }, [])

  const loadWorkbook = useCallback(async (objectId: string) => {
    setBusy(true)
    setError('')
    try {
      const opened = await api.openWorkbook(objectId)
      const [nextCatalog, nextUnsaved, nextVersions] = await Promise.all([
        api.catalog(opened.id),
        api.unsaved(opened.id),
        api.versions(opened.id),
      ])
      setWorkbook(opened)
      setCatalog(nextCatalog)
      setUnsaved(nextUnsaved)
      setVersions(nextVersions)
      setObjects((prev) =>
        prev.map((item) => (item.id === objectId ? { ...item, workbook_id: opened.id } : item)),
      )
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const timers: number[] = []
    api
      .me()
      .then(async (data) => {
        if (cancelled) return
        setUsername(data.username)
        setCanWrite(data.can_write)
        const localSeen = localStorage.getItem(GUIDE_SEEN_KEY) === '1'
        if (data.guide_seen || localSeen) {
          localStorage.setItem(GUIDE_SEEN_KEY, '1')
          if (!data.guide_seen) await api.markGuideSeen()
          return
        }
        timers.push(
          window.setTimeout(() => {
            if (!cancelled) setGuideOffer(true)
          }, 700),
        )
      })
      .catch(() => {
        if (!cancelled) setUsername('unknown')
      })
    api.objects().then(setObjects).catch((exc) => setError(String(exc)))
    return () => {
      cancelled = true
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [])

  useEffect(() => {
    const onLeave = (event: BeforeUnloadEvent) => {
      if (unsaved.length === 0) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onLeave)
    return () => window.removeEventListener('beforeunload', onLeave)
  }, [unsaved.length])

  useEffect(() => {
    if (!workbook) return
    const timer = window.setInterval(() => {
      if (unsaved.length > 0) setHelp('unsaved')
    }, 60 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [workbook, unsaved.length])

  useEffect(() => {
    const tick = () => {
      api.notifications().then(setNotes).catch(() => undefined)
    }
    tick()
    const timer = window.setInterval(tick, 30000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (help !== 'unsaved' || unsaved.length > 0) return
    setHelp(null)
    if (pendingTab) {
      setTab(pendingTab)
      setPendingTab(null)
    }
  }, [help, unsaved.length, pendingTab])

  async function selectObject(objectId: string) {
    setSelectedId(objectId)
    setMessage('')
    if (!objectId) {
      setWorkbook(null)
      setCatalog(null)
      return
    }
    await loadWorkbook(objectId)
  }

  async function tryChangeTab(next: TabId) {
    if (next !== 'object' && unsaved.length > 0) {
      setPendingTab(next)
      setHelp('unsaved')
      return
    }
    setTab(next)
    if (next === 'report' && workbook) {
      setVersions(await api.versions(workbook.id))
    }
  }

  async function openHelp(kind: Exclude<HelpKind, 'unsaved' | 'notes' | null>) {
    setHelp(kind)
    if (kind === 'instruction') setHelpText((await api.instruction()).text)
    if (kind === 'changelog') {
      const data = await api.changelog()
      setHelpText(data.text)
      setChangelogReleases(data.releases || [])
    }
    if (kind === 'user-journal') setJournalItems(await api.journal())
    if (kind === 'about') {
      setHelpText(
        `Гранд сводка ИД 0.2.6\nПользователь: ${username}\nПрава: ${canWrite ? 'ОР (запись)' : 'просмотр'}\nСистема управления исходными данными проточных частей турбин.`,
      )
    }
  }

  useEffect(() => {
    if (workbook?.id === workbookIdRef.current) return
    workbookIdRef.current = workbook?.id || null
    setUndoStack([])
    setRedoStack([])
  }, [workbook?.id])

  async function recordHistory(
    previousWorkbook: Workbook,
    previousCatalog: Catalog | null,
    label: string,
    kind: HistoryEntry['kind'],
    keys: { parameterKey?: string; columnKey?: string },
    nextWorkbook: Workbook,
    extra?: { changeIds?: string[]; changes?: HistoryEntry['after']['changes'] },
  ) {
    const nextCatalog = await api.catalog(nextWorkbook.id)
    setWorkbook(nextWorkbook)
    setCatalog(nextCatalog)
    setUnsaved(await api.unsaved(nextWorkbook.id))
    if (historyBusy.current) return nextCatalog
    const before = takeSnap(previousWorkbook, previousCatalog)
    const after = takeSnap(nextWorkbook, nextCatalog, extra)
    setUndoStack((stack) => pushEntry(stack, makeEntry(label, kind, before, after, keys)))
    setRedoStack([])
    return nextCatalog
  }

  async function applyHistory(entry: HistoryEntry, direction: 'undo' | 'redo') {
    if (!workbook) return
    historyBusy.current = true
    const target = direction === 'undo' ? entry.before : entry.after
    const other = direction === 'undo' ? entry.after : entry.before
    try {
      const next = await api.restoreSession(workbook.id, {
        cells: target.cells,
        extra_parameters: target.extra_parameters,
        parameter_overrides: target.parameter_overrides,
        deleted_parameters: target.deleted_parameters,
        remove_change_ids: direction === 'undo' ? entry.after.changeIds : [],
        add_changes: direction === 'redo' ? entry.after.changes : [],
        clear_keys: clearKeys(other.cells, target.cells).map((item) => ({
          parameter_key: item.parameter_key,
          column_key: item.column_key,
        })),
      })
      setWorkbook(next)
      setCatalog(await api.catalog(next.id))
      setUnsaved(await api.unsaved(next.id))
    } catch (exc) {
      await handleWriteError(exc)
    } finally {
      historyBusy.current = false
    }
  }

  async function undoAction() {
    if (!canWrite || busy || undoStack.length === 0) return
    const entry = undoStack[undoStack.length - 1]
    setUndoStack((stack) => stack.slice(0, -1))
    setRedoStack((stack) => [...stack, entry])
    await applyHistory(entry, 'undo')
  }

  async function redoAction() {
    if (!canWrite || busy || redoStack.length === 0) return
    const entry = redoStack[redoStack.length - 1]
    setRedoStack((stack) => stack.slice(0, -1))
    setUndoStack((stack) => [...stack, entry])
    await applyHistory(entry, 'redo')
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const ctrl = event.ctrlKey || event.metaKey
      if (!ctrl) return
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      const inField = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      const inCell = Boolean(target?.classList?.contains('cell-edit'))
      if (inField && !inCell) return
      if (event.key === 'z' && !event.shiftKey) {
        event.preventDefault()
        void undoAction()
      }
      if (event.key === 'y' || (event.key === 'z' && event.shiftKey)) {
        event.preventDefault()
        void redoAction()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undoStack, redoStack, canWrite, busy, workbook])

  async function handleWriteError(exc: unknown) {
    if (exc instanceof ApiError && exc.status === 409) {
      const detail = exc.detail as { updated_by?: string; display?: string }
      setError(
        `Значение уже изменил ${detail?.updated_by || 'другой пользователь'} (сейчас: ${detail?.display || '—'}). Обновите таблицу.`,
      )
      if (workbook) await reloadWorkbook(workbook.id)
      return
    }
    setError(exc instanceof Error ? exc.message : String(exc))
  }

  const unread = notes.filter((item) => !item.read).length
  const guideSteps = guideKind ? tourSteps(guideKind) : []

  function rememberGuideSeen() {
    localStorage.setItem(GUIDE_SEEN_KEY, '1')
    void api.markGuideSeen()
  }

  async function startGuide(kind: GuideKind) {
    rememberGuideSeen()
    setGuideOffer(false)
    setHelp(null)
    setMenuOpen(null)
    if (!workbook && objects[0]) await selectObject(objects[0].id)
    const first = tourSteps(kind)[0]
    if (first?.tab) setTab(first.tab)
    setGuideKind(kind)
    setGuideIndex(0)
  }

  function goGuide(nextIndex: number) {
    if (!guideKind) return
    const steps = tourSteps(guideKind)
    if (nextIndex >= steps.length) {
      rememberGuideSeen()
      setGuideKind(null)
      return
    }
    if (nextIndex < 0) return
    const step = steps[nextIndex]
    if (step.tab && (step.tab === 'object' || workbook)) setTab(step.tab)
    setGuideIndex(nextIndex)
  }

  return (
    <div className="app" onClick={() => setMenuOpen(null)}>
      <div className="menubar" data-guide="guide-menu">
        <div className={`menu ${menuOpen === 'file' ? 'open' : ''}`}>
          <button
            type="button"
            className="menu-btn"
            onClick={(event) => {
              event.stopPropagation()
              setMenuOpen(menuOpen === 'file' ? null : 'file')
            }}
          >
            Файл
          </button>
          {menuOpen === 'file' ? (
            <div className="menu-drop">
              <button type="button" onClick={() => window.location.reload()}>
                Обновить
              </button>
            </div>
          ) : null}
        </div>
        <div className="undo-btns" data-guide="guide-undo">
          <button
            type="button"
            className="menu-btn undo-btn"
            title={undoStack.length ? `Отменить: ${undoStack[undoStack.length - 1].label} (Ctrl+Z)` : 'Отменить (Ctrl+Z)'}
            disabled={!canWrite || busy || undoStack.length === 0}
            onClick={(event) => {
              event.stopPropagation()
              void undoAction()
            }}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M4.5 6.5H10a3.5 3.5 0 1 1 0 7H8.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
              <path d="M4.5 6.5 L7 4 M4.5 6.5 L7 9" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            className="menu-btn undo-btn"
            title={redoStack.length ? `Повторить: ${redoStack[redoStack.length - 1].label} (Ctrl+Y)` : 'Повторить (Ctrl+Y)'}
            disabled={!canWrite || busy || redoStack.length === 0}
            onClick={(event) => {
              event.stopPropagation()
              void redoAction()
            }}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M11.5 6.5H6a3.5 3.5 0 1 0 0 7H7.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
              <path d="M11.5 6.5 L9 4 M11.5 6.5 L9 9" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className={`menu ${menuOpen === 'help' ? 'open' : ''}`}>
          <button
            type="button"
            className="menu-btn"
            onClick={(event) => {
              event.stopPropagation()
              setMenuOpen(menuOpen === 'help' ? null : 'help')
            }}
          >
            Справка
          </button>
          {menuOpen === 'help' ? (
            <div className="menu-drop">
              <button type="button" onClick={() => openHelp('instruction')}>
                Инструкция
              </button>
              <button type="button" onClick={() => openHelp('about')}>
                О приложении
              </button>
              <button type="button" onClick={() => openHelp('changelog')}>
                Журнал изменений приложения
              </button>
              <button type="button" onClick={() => openHelp('user-journal')}>
                Журнал изменений пользователей
              </button>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(null)
                  setGuideOffer(true)
                }}
              >
                Обучение
              </button>
            </div>
          ) : null}
        </div>
        <button
          type="button"
          className="menu-btn"
          data-guide="guide-notes"
          onClick={(event) => {
            event.stopPropagation()
            setHelp('notes')
          }}
        >
          Уведомления{unread ? ` (${unread})` : ''}
        </button>
        <button
          type="button"
          className="menu-btn guide-help"
          data-guide="guide-help"
          title="Обучение"
          onClick={(event) => {
            event.stopPropagation()
            setGuideOffer(true)
          }}
        >
          ?
        </button>
        <div className="user-chip">
          Пользователь: {username || '…'}
          {canWrite ? '' : ' (просмотр)'}
        </div>
      </div>

      <div className="workspace">
        {error ? <div className="warn">{error}</div> : null}
        {message ? <div className="ok">{message}</div> : null}
        <div className="tabs" data-guide="guide-tabs">
          <button
            type="button"
            className={`tab ${tab === 'object' ? 'active' : ''}`}
            onClick={() => tryChangeTab('object')}
          >
            Объект и треугольники
          </button>
          <button
            type="button"
            className={`tab ${tab === 'table' ? 'active' : ''}`}
            data-guide="guide-tab-table"
            disabled={!workbook}
            onClick={() => tryChangeTab('table')}
          >
            Таблица ИД
          </button>
          <button
            type="button"
            className={`tab ${tab === 'report' ? 'active' : ''}`}
            data-guide="guide-tab-report"
            disabled={!workbook}
            onClick={() => tryChangeTab('report')}
          >
            Отчёт
          </button>
        </div>

        {tab === 'object' ? (
          <ObjectTab
            objects={objects}
            selectedId={selectedId}
            workbook={workbook}
            busy={busy}
            message=""
            canWrite={canWrite}
            onSelect={selectObject}
            onSyncObjects={async () => {
              setObjects(await api.syncObjects())
              setMessage('Объекты синхронизированы из каталога')
            }}
            onCreate={async (payload) => {
              setBusy(true)
              try {
                const created = await api.createObject(payload)
                const list = await api.objects()
                setObjects(list)
                await selectObject(created.id)
                setMessage('Объект создан')
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
            }}
            onImportObjects={async (file) => {
              setBusy(true)
              try {
                setObjects(await api.importObjects(file))
                setMessage('Список объектов обновлён')
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
            }}
            onImportTriangle={async (file) => {
              if (!workbook) return
              setBusy(true)
              try {
                const next = await api.importTriangle(workbook.id, file)
                setWorkbook(next)
                setMessage(`Импортировано значений: ${next.imported ?? 0}. Создана версия 0.`)
                setVersions(await api.versions(next.id))
                await refreshUnsaved(next.id)
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
            }}
            onAddStage={async (label) => {
              if (!workbook) return
              await api.addStage(workbook.id, label)
              setCatalog(await api.catalog(workbook.id))
              setMessage(`Добавлена ступень ${label}`)
            }}
          />
        ) : null}

        {tab === 'table' ? (
          <TableTab
            catalog={catalog}
            workbook={workbook}
            unsaved={unsaved}
            history={history}
            busy={busy}
            canWrite={canWrite}
            onSelectCell={async (selection) => {
              if (!workbook) return
              setHistory(await api.history(workbook.id, selection.parameterKey, selection.columnKey))
            }}
            onAddParameter={async (body) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.addParameter(workbook.id, body)
              const next = await api.workbook(workbook.id)
              await recordHistory(previous, previousCatalog, 'Добавление параметра', 'structure', {}, next)
            }}
            onUpdateParameter={async (key, body) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.updateParameter(workbook.id, key, body)
              const next = await api.workbook(workbook.id)
              await recordHistory(previous, previousCatalog, 'Изменение параметра', 'structure', { parameterKey: key }, next)
            }}
            onDeleteParameter={async (key) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.deleteParameter(workbook.id, key)
              const next = await api.workbook(workbook.id)
              await recordHistory(previous, previousCatalog, 'Удаление параметра', 'structure', { parameterKey: key }, next)
            }}
            onDiscard={async (parameterKey, columnKey) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.discardCell(workbook.id, parameterKey, columnKey)
              const next = await api.workbook(workbook.id)
              await recordHistory(
                previous,
                previousCatalog,
                'Отмена черновика',
                'discard',
                { parameterKey, columnKey },
                next,
              )
            }}
            onDraft={async (parameterKey, columnKey, value, hyperlink) => {
              if (!workbook) return
              try {
                const previous = workbook
                const previousCatalog = catalog
                await api.patchCell(workbook.id, parameterKey, columnKey, {
                  value,
                  hyperlink,
                  expected_updated_at: expectedAt(workbook, parameterKey, columnKey),
                })
                const next = await api.workbook(workbook.id)
                await recordHistory(
                  previous,
                  previousCatalog,
                  'Ввод в ячейке',
                  'draft',
                  { parameterKey, columnKey },
                  next,
                )
              } catch (exc) {
                await handleWriteError(exc)
              }
            }}
            onConfirm={async (parameterKey, columnKey, value, comment, hyperlink) => {
              if (!workbook) return
              try {
                const previous = workbook
                const previousCatalog = catalog
                const cell = await api.confirmCell(workbook.id, parameterKey, columnKey, {
                  value,
                  comment,
                  hyperlink,
                  expected_updated_at: expectedAt(workbook, parameterKey, columnKey),
                })
                const next = await api.workbook(workbook.id)
                const log = await api.history(workbook.id, parameterKey, columnKey)
                setHistory(log)
                const last = log[0]
                await recordHistory(
                  previous,
                  previousCatalog,
                  'Сохранение значения',
                  'confirm',
                  { parameterKey, columnKey },
                  next,
                  {
                    changeIds: cell.last_change_id ? [cell.last_change_id] : last ? [last.id] : [],
                    changes: last
                      ? [
                          {
                            id: last.id,
                            parameter_key: parameterKey,
                            column_key: columnKey,
                            author: last.author,
                            old_value: last.old_value,
                            new_value: last.new_value,
                            comment: last.comment,
                          },
                        ]
                      : [],
                  },
                )
              } catch (exc) {
                await handleWriteError(exc)
              }
            }}
          />
        ) : null}

        {tab === 'report' ? (
          <ReportTab
            workbook={workbook}
            versions={versions}
            tables={tables}
            busy={busy}
            canWrite={canWrite}
            onPreview={async (type, versionId) => {
              if (!workbook) return
              const preview = await api.reportPreview(workbook.id, type, versionId || null)
              setTables(preview.tables)
            }}
            onCreate={async (type, versionId, extraNotes) => {
              if (!workbook) return
              const blob = await api.createReport(workbook.id, type, versionId || null, extraNotes)
              const url = URL.createObjectURL(blob)
              const link = document.createElement('a')
              link.href = url
              link.download = `grand_summary_${type}.docx`
              link.click()
              URL.revokeObjectURL(url)
              setVersions(await api.versions(workbook.id))
              setMessage('Сводка сохранена, создан снимок версии')
            }}
            onRestore={async (versionId) => {
              if (!workbook) return
              const next = await api.restoreVersion(workbook.id, versionId)
              setWorkbook(next)
              setMessage('Загружена выбранная версия')
            }}
            onIssue={async (description) => {
              if (!workbook) return
              await api.createVersion(workbook.id, 'issued', description)
              setVersions(await api.versions(workbook.id))
              setMessage('Версия зафиксирована как выданная')
            }}
          />
        ) : null}
      </div>

      {help === 'unsaved' ? (
        <Dialog
          title="Несохранённые ячейки"
          onClose={() => {
            setHelp(null)
            setPendingTab(null)
          }}
          actions={
            pendingTab ? (
              <button
                type="button"
                className="win-btn"
                onClick={() => {
                  if (pendingTab) setTab(pendingTab)
                  setPendingTab(null)
                  setHelp(null)
                }}
              >
                Всё равно перейти
              </button>
            ) : null
          }
        >
          <p>Жёлтых ячеек быть не должно. Сохраните с комментарием или отмените черновик:</p>
          <ul className="list">
            {unsaved.map((item) => {
              const key = `${item.parameter_key}:${item.column_key}`
              return (
                <li key={key}>
                  {item.parameter_label} / {item.column_label}: {item.draft_value}
                  <div className="toolbar" style={{ marginTop: 6 }}>
                    <input
                      type="text"
                      placeholder="Комментарий"
                      value={unsavedComments[key] || ''}
                      onChange={(event) =>
                        setUnsavedComments((prev) => ({ ...prev, [key]: event.target.value }))
                      }
                    />
                    <button
                      type="button"
                      className="win-btn"
                      disabled={!workbook || !(unsavedComments[key] || '').trim()}
                      onClick={async () => {
                        if (!workbook) return
                        await api.confirmCell(workbook.id, item.parameter_key, item.column_key, {
                          value: item.draft_value,
                          comment: (unsavedComments[key] || '').trim(),
                          expected_updated_at: expectedAt(
                            workbook,
                            item.parameter_key,
                            item.column_key,
                          ),
                        })
                        await reloadWorkbook(workbook.id)
                      }}
                    >
                      Сохранить
                    </button>
                    <button
                      type="button"
                      className="win-btn"
                      onClick={async () => {
                        if (!workbook) return
                        await api.discardCell(workbook.id, item.parameter_key, item.column_key)
                        await reloadWorkbook(workbook.id)
                      }}
                    >
                      Отменить
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </Dialog>
      ) : null}

      {help === 'notes' ? (
        <Dialog title="Уведомления" onClose={() => setHelp(null)}>
          {notes.length === 0 ? (
            <p>Нет уведомлений</p>
          ) : (
            <ul className="list">
              {notes.map((item) => (
                <li key={item.id}>
                  {item.read ? '' : '• '}
                  {item.message} ({new Date(item.created_at).toLocaleString()})
                  {item.read ? null : (
                    <button
                      type="button"
                      className="win-btn"
                      onClick={async () => {
                        await api.readNotification(item.id)
                        setNotes(await api.notifications())
                      }}
                    >
                      Прочитано
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Dialog>
      ) : null}

      {help === 'changelog' ? (
        <Dialog title="Журнал изменений приложения" onClose={() => setHelp(null)} wide>
          <ChangelogViewer releases={changelogReleases} />
        </Dialog>
      ) : null}

      {help === 'user-journal' ? (
        <Dialog title="Журнал изменений пользователей" onClose={() => setHelp(null)} wide>
          <UserJournal items={journalItems} />
        </Dialog>
      ) : null}

      {help && help !== 'unsaved' && help !== 'notes' && help !== 'changelog' && help !== 'user-journal' ? (
        <Dialog
          title={help === 'about' ? 'О приложении' : 'Инструкция'}
          onClose={() => setHelp(null)}
        >
          {helpText}
        </Dialog>
      ) : null}

      {guideOffer && !guideKind ? (
        <GuideChoice
          onPick={(kind) => {
            void startGuide(kind)
          }}
          onClose={() => {
            rememberGuideSeen()
            setGuideOffer(false)
          }}
        />
      ) : null}

      {guideKind ? (
        <GuideOverlay
          steps={guideSteps}
          index={guideIndex}
          onBack={() => goGuide(guideIndex - 1)}
          onNext={() => goGuide(guideIndex + 1)}
          onSkip={() => {
            rememberGuideSeen()
            setGuideKind(null)
          }}
        />
      ) : null}
    </div>
  )
}
