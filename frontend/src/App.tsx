import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, type HistoryPreferences } from './api'
import { ChangelogViewer } from './components/ChangelogViewer'
import { Dialog } from './components/Dialog'
import { GuideChoice, GuideOverlay } from './components/Guide'
import { ObjectTab } from './components/ObjectTab'
import { ReportTab } from './components/ReportTab'
import { TableTab } from './components/TableTab'
import { TriangleTab } from './components/TriangleTab'
import { UserJournal } from './components/UserJournal'
import { GUIDE_SEEN_KEY, tourSteps, type GuideKind } from './guide'
import { clearKeys, makeEntry, pushEntry, takeSnap, type HistoryEntry } from './sessionHistory'
import type {
  Catalog,
  Cell,
  CellChange,
  ChangelogRelease,
  JournalItem,
  NotificationItem,
  ObjectItem,
  TabId,
  TriangleSheetData,
  UnsavedCell,
  VersionItem,
  Workbook,
  WorkbookSheet,
} from './types'

type HelpKind = 'instruction' | 'about' | 'changelog' | 'unsaved' | 'notes' | 'user-journal' | null

const HISTORY_POSITION_KEY = 'grand-summary.history.position'
const HISTORY_PANEL_OPEN_KEY = 'grand-summary.history.panel-open'
const HISTORY_SIZES_KEY = 'grand-summary.history.sizes'

function boundedPreference(value: unknown, fallback: number, minimum: number, maximum: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.max(minimum, Math.min(maximum, Math.round(value)))
}

function loadLocalHistoryPreferences(): HistoryPreferences {
  let savedSizes: { right?: unknown; bottom?: unknown } = {}
  try {
    savedSizes = JSON.parse(localStorage.getItem(HISTORY_SIZES_KEY) || '{}') as typeof savedSizes
  } catch {
    savedSizes = {}
  }
  return {
    history_position: localStorage.getItem(HISTORY_POSITION_KEY) === 'bottom' ? 'bottom' : 'right',
    history_panel_open: localStorage.getItem(HISTORY_PANEL_OPEN_KEY) !== 'false',
    history_right_width: boundedPreference(savedSizes.right, 360, 100, 760),
    history_bottom_height: boundedPreference(savedSizes.bottom, 260, 140, 600),
  }
}

function expectedAt(workbook: Workbook | null, parameterKey: string, columnKey: string) {
  const cell = workbook?.cells.find(
    (item) => item.parameter_key === parameterKey && item.column_key === columnKey,
  )
  return cell?.updated_at ?? null
}

function workbookWithCell(workbook: Workbook, updatedCell: Cell): Workbook {
  const index = workbook.cells.findIndex(
    (cell) =>
      cell.parameter_key === updatedCell.parameter_key &&
      cell.column_key === updatedCell.column_key,
  )
  const previousCell = index >= 0 ? workbook.cells[index] : null
  const cells = [...workbook.cells]
  if (index >= 0) cells[index] = updatedCell
  else cells.push(updatedCell)

  return {
    ...workbook,
    cells,
    updated_at: updatedCell.updated_at || workbook.updated_at,
    unsaved_count: Math.max(
      0,
      workbook.unsaved_count + Number(updatedCell.status === 'draft') - Number(previousCell?.status === 'draft'),
    ),
  }
}

export default function App() {
  const [username, setUsername] = useState('')
  const [canWrite, setCanWrite] = useState(true)
  const [objects, setObjects] = useState<ObjectItem[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [workbook, setWorkbook] = useState<Workbook | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const loadTargetCatalog = useCallback((sheetId: string) => api.catalog(sheetId), [])
  const [sheetItems, setSheetItems] = useState<WorkbookSheet[]>([])
  const [triangleSheets, setTriangleSheets] = useState<TriangleSheetData[]>([])
  const [tab, setTab] = useState<TabId>('object')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [menuOpen, setMenuOpen] = useState<'file' | 'view' | 'help' | 'notes' | null>(null)
  const [historyPreferences, setHistoryPreferences] = useState(loadLocalHistoryPreferences)
  const [historyPreferencesLoaded, setHistoryPreferencesLoaded] = useState(false)
  const historyPosition = historyPreferences.history_position
  const historyPanelOpen = historyPreferences.history_panel_open
  const [help, setHelp] = useState<HelpKind>(null)
  const [helpText, setHelpText] = useState('')
  const [history, setHistory] = useState<CellChange[]>([])
  const [unsaved, setUnsaved] = useState<UnsavedCell[]>([])
  const [, setVersions] = useState<VersionItem[]>([])
  const [reportTableData, setReportTableData] = useState<{ sheetId: string; catalog: Catalog; workbook: Workbook } | null>(null)
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
  const projectRevisionRef = useRef<string | null>(null)
  const revisionPollInFlight = useRef(false)
  const workbookLoadGenerationRef = useRef(0)

  useEffect(() => {
    localStorage.setItem(HISTORY_POSITION_KEY, historyPreferences.history_position)
    localStorage.setItem(HISTORY_PANEL_OPEN_KEY, String(historyPreferences.history_panel_open))
    localStorage.setItem(
      HISTORY_SIZES_KEY,
      JSON.stringify({
        right: historyPreferences.history_right_width,
        bottom: historyPreferences.history_bottom_height,
      }),
    )
  }, [historyPreferences])

  useEffect(() => {
    if (!historyPreferencesLoaded) return
    const timeout = window.setTimeout(() => {
      void api.saveHistoryPreferences(historyPreferences).catch((exc) => {
        setError(exc instanceof Error ? exc.message : String(exc))
      })
    }, 150)
    return () => window.clearTimeout(timeout)
  }, [historyPreferences, historyPreferencesLoaded])

  useEffect(() => {
    if (!historyPreferencesLoaded) return
    const saveBeforeClose = () => {
      void api.saveHistoryPreferences(historyPreferences, true).catch(() => undefined)
    }
    window.addEventListener('pagehide', saveBeforeClose)
    return () => window.removeEventListener('pagehide', saveBeforeClose)
  }, [historyPreferences, historyPreferencesLoaded])

  const reloadWorkbook = useCallback(async (workbookId: string) => {
    const generation = ++workbookLoadGenerationRef.current
    const startingRevision = await api.workbookRevision(workbookId)
    const [next, nextCatalog, nextUnsaved] = await Promise.all([
      api.workbook(workbookId),
      api.catalog(workbookId),
      api.unsaved(workbookId),
    ])
    if (generation !== workbookLoadGenerationRef.current) return
    setWorkbook(next)
    setCatalog(nextCatalog)
    setUnsaved(nextUnsaved)
    projectRevisionRef.current = startingRevision.revision
  }, [])

  const loadWorkbook = useCallback(async (objectId: string) => {
    const generation = ++workbookLoadGenerationRef.current
    setBusy(true)
    setError('')
    try {
      const opened = await api.openWorkbook(objectId)
      const [startingRevision, nextSheets] = await Promise.all([
        api.workbookRevision(opened.id),
        api.sheets(opened.id),
      ])
      const activeWorkbookId = nextSheets[0]?.id ?? opened.id
      const [currentWorkbook, nextCatalog, nextUnsaved, nextVersions, nextTriangles] =
        await Promise.all([
          api.workbook(activeWorkbookId),
          api.catalog(activeWorkbookId),
          api.unsaved(activeWorkbookId),
          api.versions(activeWorkbookId),
          api.triangles(opened.id),
        ])
      if (generation !== workbookLoadGenerationRef.current) return
      setWorkbook(currentWorkbook)
      setCatalog(nextCatalog)
      setUnsaved(nextUnsaved)
      setVersions(nextVersions)
      setSheetItems(nextSheets)
      setTriangleSheets(nextTriangles)
      projectRevisionRef.current = startingRevision.revision
      setObjects((prev) =>
        prev.map((item) => (item.id === objectId ? { ...item, workbook_id: opened.id } : item)),
      )
    } catch (exc) {
      if (generation === workbookLoadGenerationRef.current) {
        setError(exc instanceof Error ? exc.message : String(exc))
      }
    } finally {
      if (generation === workbookLoadGenerationRef.current) setBusy(false)
    }
  }, [])

  async function loadSheetData(sheetId: string) {
    const generation = ++workbookLoadGenerationRef.current
    const knownRootWorkbookId = workbook?.parent_workbook_id || workbook?.id
    const [nextWorkbook, startingRevision] = await Promise.all([
      api.workbook(sheetId),
      knownRootWorkbookId ? api.workbookRevision(knownRootWorkbookId) : Promise.resolve(null),
    ])
    const rootWorkbookId = nextWorkbook.parent_workbook_id || nextWorkbook.id
    const projectRevision = startingRevision || await api.workbookRevision(rootWorkbookId)
    const [nextCatalog, nextUnsaved, nextVersions, nextSheets, nextTriangles] = await Promise.all([
      api.catalog(nextWorkbook.id),
      api.unsaved(nextWorkbook.id),
      api.versions(nextWorkbook.id),
      api.sheets(rootWorkbookId),
      api.triangles(rootWorkbookId),
    ])
    if (generation !== workbookLoadGenerationRef.current) return
    setWorkbook(nextWorkbook)
    setCatalog(nextCatalog)
    setUnsaved(nextUnsaved)
    setVersions(nextVersions)
    setSheetItems(nextSheets)
    setTriangleSheets(nextTriangles)
    projectRevisionRef.current = projectRevision.revision
    setHistory([])
    setUndoStack([])
    setRedoStack([])
  }

  async function selectSheet(sheetId: string) {
    if (unsaved.length > 0) {
      setError('Сначала сохраните или отмените черновики текущего листа.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await loadSheetData(sheetId)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function copyCurrentSheet(sourceSheetId?: string) {
    if (!workbook || !canWrite) return
    const sourceId = sourceSheetId || workbook.id
    const source = sheetItems.find((sheet) => sheet.id === sourceId)
    if (!source) return
    if (unsaved.length > 0) {
      setError('Сначала сохраните или отмените черновики текущего листа.')
      return
    }
    const name = window.prompt('Название нового листа', `${source.name} — копия`)
    if (!name?.trim()) return
    setBusy(true)
    setError('')
    try {
      const copy = await api.copySheet(sourceId, name.trim())
      await loadSheetData(copy.id)
      setMessage(`Создан лист «${copy.sheet_name}» с копией структуры и значений.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function renameSheetById(sheetId: string) {
    if (!workbook || !canWrite) return
    const target = sheetItems.find((sheet) => sheet.id === sheetId)
    if (!target) return
    const name = window.prompt('Новое название листа', target.name)
    if (!name?.trim() || name.trim() === target.name) return
    setBusy(true)
    setError('')
    try {
      const rootWorkbookId = workbook.parent_workbook_id || workbook.id
      const renamed = await api.renameSheet(rootWorkbookId, sheetId, name.trim())
      const [nextSheets, revision] = await Promise.all([
        api.sheets(rootWorkbookId),
        api.workbookRevision(rootWorkbookId),
      ])
      if (workbook.id === sheetId) setWorkbook(renamed)
      setSheetItems(nextSheets)
      projectRevisionRef.current = revision.revision
      setMessage(`Лист переименован в «${renamed.sheet_name}».`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function setPrimarySheet(sheetId: string) {
    if (!workbook || !canWrite) return
    const target = sheetItems.find((sheet) => sheet.id === sheetId)
    if (!target || target.is_primary) return
    const currentPrimary = sheetItems.find((sheet) => sheet.is_primary)
    if (currentPrimary && !window.confirm(
      `Основной лист сейчас «${currentPrimary.name}». Уверены, что хотите сделать лист «${target.name}» основным? Он будет перемещён в начало списка.`,
    )) return

    setBusy(true)
    setError('')
    try {
      const rootWorkbookId = workbook.parent_workbook_id || workbook.id
      const result = await api.setPrimarySheet(rootWorkbookId, sheetId)
      const revision = await api.workbookRevision(rootWorkbookId)
      setSheetItems(result.sheets)
      setWorkbook((current) => current
        ? { ...current, is_primary: result.sheets.find((sheet) => sheet.id === current.id)?.is_primary ?? current.is_primary }
        : current)
      projectRevisionRef.current = revision.revision
      setMessage(`Лист «${target.name}» назначен основным и перемещён в начало.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function unsetPrimarySheet(sheetId: string) {
    if (!workbook || !canWrite) return
    const target = sheetItems.find((sheet) => sheet.id === sheetId)
    if (!target?.is_primary) return

    setBusy(true)
    setError('')
    try {
      const rootWorkbookId = workbook.parent_workbook_id || workbook.id
      const result = await api.unsetPrimarySheet(rootWorkbookId, sheetId)
      const revision = await api.workbookRevision(rootWorkbookId)
      setSheetItems(result.sheets)
      setWorkbook((current) => current
        ? { ...current, is_primary: result.sheets.find((sheet) => sheet.id === current.id)?.is_primary ?? current.is_primary }
        : current)
      projectRevisionRef.current = revision.revision
      setMessage(`С листа «${target.name}» снят статус основного.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function deleteSheetById(sheetId: string) {
    if (!workbook || !canWrite) return
    const rootWorkbookId = workbook.parent_workbook_id || workbook.id
    const target = sheetItems.find((sheet) => sheet.id === sheetId)
    if (!target || sheetItems.length <= 1) return
    if (sheetId === workbook.id && unsaved.length > 0) {
      setError('Сначала сохраните или отмените черновики текущего листа.')
      return
    }
    if (!window.confirm(`Удалить лист «${target.name}»?`)) return
    setBusy(true)
    setError('')
    try {
      const result = await api.deleteSheet(rootWorkbookId, sheetId)
      setSheetItems(result.sheets)
      if (workbook.id === sheetId || sheetId === rootWorkbookId) {
        await loadSheetData(result.active_sheet_id)
      } else {
        const revision = await api.workbookRevision(rootWorkbookId)
        projectRevisionRef.current = revision.revision
      }
      setMessage(`Лист «${target.name}» удалён.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  function composeReportFromCurrentSheet() {
    if (!workbook) return
    if (unsaved.length > 0) {
      setError('Сначала сохраните или отмените черновики текущего листа.')
      return
    }
    setReportTableData(null)
    setTab('report')
  }

  async function importWorkingWorkbook(file: File) {
    if (!selectedId || !canWrite) return
    if (unsaved.length > 0) {
      setError('Сначала сохраните или отмените черновики текущего листа.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const rootWorkbook = await api.openWorkbook(selectedId)
      const result = await api.importWorkbook(rootWorkbook.id, file)
      await loadSheetData(result.active_sheet_id)
      setMessage(`Импортировано листов: ${result.imported}.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function saveCurrentProject() {
    if (!workbook || !canWrite) return
    setBusy(true)
    setError('')
    try {
      const rootWorkbookId = workbook.parent_workbook_id || workbook.id
      const result = await api.saveProject(rootWorkbookId)
      setMessage(
        `Проект сохранён: листов ${result.sheet_count}, ячеек ${result.cell_count}, черновиков ${result.draft_count}. Статусы оставлены без изменений.`,
      )
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function exportWorkbookToExcel(scope: 'current' | 'all') {
    if (!workbook) return
    setBusy(true)
    setError('')
    try {
      const blob = await api.exportExcel(workbook.id, scope)
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const projectName = (workbook.object.name || 'grand_summary').replace(/[\\/:*?"<>|]+/g, '_')
      link.href = objectUrl
      link.download = `${projectName}_${scope === 'all' ? 'all_sheets' : 'current_sheet'}.xlsx`
      link.click()
      URL.revokeObjectURL(objectUrl)
      setMessage(scope === 'all' ? 'Выгружены листы проекта и проверки.' : 'Текущий лист выгружен в Excel.')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function exportReportTableToWord(
    sheetId: string,
    parameterKeys: string[],
    columnKeys: string[],
    tableNumber: number,
  ) {
    setBusy(true)
    setError('')
    try {
      const blob = await api.exportReportTableDocx(sheetId, parameterKeys, columnKeys, tableNumber)
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const projectName = (workbook?.object.name || 'grand_summary').replace(/[\\/:*?"<>|]+/g, '_')
      link.href = objectUrl
      link.download = `${projectName}_таблица_${tableNumber}.docx`
      link.click()
      URL.revokeObjectURL(objectUrl)
      setMessage(`Таблица ${tableNumber} выгружена в Word.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  async function refreshApplication() {
    setMenuOpen(null)
    setError('')
    setBusy(true)
    try {
      const status = await api.updateStatus()
      if (!status.supported) {
        window.location.reload()
        return
      }
      if (!status.enabled) {
        setMessage(status.message || 'Источник обновлений не настроен.')
        return
      }
      if (!status.update_available) {
        setMessage(`Установлена последняя версия (${status.current_version}).`)
        return
      }
      const latest = status.latest_version || 'новая версия'
      if (!window.confirm(`Доступна версия ${latest}. Обновить и перезапустить приложение?`)) return
      const result = await api.applyUpdate()
      setMessage(`Обновление до версии ${result.version} запущено. Приложение перезапустится.`)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const timers: number[] = []
    api
      .me()
      .then(async (data) => {
        if (cancelled) return
        setUsername(data.username)
        setCanWrite(data.can_write)
        try {
          const preferences = await api.historyPreferences()
          if (cancelled) return
          if (preferences.configured) {
            setHistoryPreferences({
              history_position: preferences.history_position,
              history_panel_open: preferences.history_panel_open,
              history_right_width: preferences.history_right_width,
              history_bottom_height: preferences.history_bottom_height,
            })
          }
          setHistoryPreferencesLoaded(true)
        } catch {
          if (!cancelled) setHistoryPreferencesLoaded(true)
        }
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
    if (!workbook || busy) return
    const pollProject = async () => {
      if (revisionPollInFlight.current || document.visibilityState !== 'visible') return
      const generation = workbookLoadGenerationRef.current
      revisionPollInFlight.current = true
      try {
        const { revision } = await api.workbookRevision(workbook.id)
        if (
          generation !== workbookLoadGenerationRef.current ||
          workbook.id !== workbookIdRef.current
        ) return
        if (!projectRevisionRef.current) {
          projectRevisionRef.current = revision
          return
        }
        if (revision === projectRevisionRef.current) return
        const activeElement = document.activeElement
        if (
          activeElement instanceof HTMLElement &&
          activeElement.matches('.sheet input.cell-edit, .side-fixed input[placeholder^="Ссылка"]')
        ) {
          return
        }
        try {
          await loadSheetData(workbook.id)
        } catch (exc) {
          if (!(exc instanceof ApiError) || exc.status !== 404 || !workbook.parent_workbook_id) {
            throw exc
          }
          await loadSheetData(workbook.parent_workbook_id)
        }
      } catch {
        // Retry on the next polling interval; temporary network errors must not interrupt editing.
      } finally {
        revisionPollInFlight.current = false
      }
    }
    void pollProject()
    const timer = window.setInterval(() => void pollProject(), 10000)
    return () => window.clearInterval(timer)
  }, [workbook?.id, workbook?.parent_workbook_id, busy])

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
    setTab('object')
    if (!objectId) {
      setWorkbook(null)
      setCatalog(null)
      setSheetItems([])
      setTriangleSheets([])
      setUnsaved([])
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
      const data = await api.changelog()
      setHelpText(
        `Гранд сводка ИД ${data.app_version}\nПользователь: ${username}\nПрава: ${canWrite ? 'ОР (запись)' : 'просмотр'}\nСистема управления исходными данными проточных частей турбин.`,
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
    const cellOnlyChange = kind === 'draft' || kind === 'confirm' || kind === 'discard'
    const [nextCatalog, nextUnsaved] = await Promise.all([
      cellOnlyChange ? Promise.resolve(previousCatalog) : api.catalog(nextWorkbook.id),
      api.unsaved(nextWorkbook.id),
    ])
    setWorkbook(nextWorkbook)
    if (nextCatalog !== previousCatalog) setCatalog(nextCatalog)
    setUnsaved(nextUnsaved)
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
        extra_columns: target.extra_columns,
        column_overrides: target.column_overrides,
        deleted_columns: target.deleted_columns,
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
              <button type="button" disabled={busy} onClick={() => void refreshApplication()}>
                Обновить
              </button>
            </div>
          ) : null}
        </div>
        <div className={`menu ${menuOpen === 'view' ? 'open' : ''}`}>
          <button
            type="button"
            className="menu-btn"
            aria-haspopup="menu"
            aria-expanded={menuOpen === 'view'}
            onClick={(event) => {
              event.stopPropagation()
              setMenuOpen(menuOpen === 'view' ? null : 'view')
            }}
          >
            Представление
          </button>
          {menuOpen === 'view' ? (
            <div className="menu-drop" role="menu" aria-label="Представление">
              <strong className="menu-section-title">История изменений</strong>
              <button
                type="button"
                role="menuitemcheckbox"
                aria-checked={historyPanelOpen}
                onClick={() =>
                  setHistoryPreferences((current) => ({
                    ...current,
                    history_panel_open: !current.history_panel_open,
                  }))
                }
              >
                {historyPanelOpen ? 'Скрыть панель истории' : 'Показать панель истории'}
              </button>
              <strong className="menu-section-title">Расположение панели</strong>
              <button
                type="button"
                role="menuitemradio"
                aria-checked={historyPosition === 'right'}
                onClick={() =>
                  setHistoryPreferences((current) => ({ ...current, history_position: 'right' }))
                }
              >
                {historyPosition === 'right' ? '✓ Справа' : 'Справа'}
              </button>
              <button
                type="button"
                role="menuitemradio"
                aria-checked={historyPosition === 'bottom'}
                onClick={() =>
                  setHistoryPreferences((current) => ({ ...current, history_position: 'bottom' }))
                }
              >
                {historyPosition === 'bottom' ? '✓ Снизу' : 'Снизу'}
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
          {triangleSheets.length > 0 ? (
            <button
              type="button"
              className={`tab ${tab === 'triangles' ? 'active' : ''}`}
              disabled={!workbook}
              onClick={() => tryChangeTab('triangles')}
            >
              Треугольники
            </button>
          ) : null}
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
            onCreate={async (payload) => {
              setBusy(true)
              try {
                const created = await api.createObject(payload)
                setObjects(await api.objects())
                await selectObject(created.id)
                setMessage('Объект добавлен в общий каталог')
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
            }}
            onImportObjectParameters={(file) => void importWorkingWorkbook(file)}
            onImportTriangle={async (file) => {
              if (!workbook) return
              setBusy(true)
              setError('')
              try {
                const rootWorkbookId = workbook.parent_workbook_id || workbook.id
                const result = await api.importTriangle(rootWorkbookId, file)
                setTriangleSheets(result.sheets)
                setTab('triangles')
                setMessage('Импортированы листы «Геом. данные» и «Проточная часть».')
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
            }}
          />
        ) : null}

        {tab === 'triangles' ? (
          <TriangleTab
            sheets={triangleSheets}
            targetSheets={sheetItems}
            canWrite={canWrite}
            busy={busy}
            onLoadCatalog={loadTargetCatalog}
            onSync={async (targetSheetId, mode, cells, targetParameterKey) => {
              if (!workbook || !canWrite) return
              if (
                mode === 'all' &&
                !window.confirm(
                  'Все сопоставимые параметры треугольников заменят соответствующие значения в выбранном листе ИД. Продолжить?',
                )
              ) return
              setBusy(true)
              setError('')
              try {
                const pending = await api.unsaved(targetSheetId)
                if (pending.length) {
                  setError('Сначала сохраните или отмените черновики на выбранном листе ИД.')
                  return
                }
                const result = await api.syncTriangles(targetSheetId, {
                  mode,
                  cells,
                  target_parameter_key: targetParameterKey,
                })
                await loadSheetData(targetSheetId)
                setTab('table')
                const unsupported = result.unsupported_fields.length
                  ? ` Не перенесены поля без однозначного соответствия: ${result.unsupported_fields.join(', ')}.`
                  : ''
                setMessage(
                  `Треугольники синхронизированы: записано ${result.updated}, очищено ${result.cleared}, пропущено ${result.skipped + result.conflicts}.${unsupported}`,
                )
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
            }}
          />
        ) : null}

        {tab === 'table' ? (
          <TableTab
            objectName={objects.find((item) => item.id === selectedId)?.name ?? ''}
            catalog={catalog}
            workbook={workbook}
            unsaved={unsaved}
            history={history}
            sheets={sheetItems}
            busy={busy}
            canWrite={canWrite}
            historyPosition={historyPosition}
            historyPanelOpen={historyPanelOpen}
            onShowHistory={() =>
              setHistoryPreferences((current) => ({ ...current, history_panel_open: true }))
            }
            onHideHistory={() =>
              setHistoryPreferences((current) => ({ ...current, history_panel_open: false }))
            }
            onSaveAllDrafts={() => {
              setUnsavedComments({})
              setHelp('unsaved')
            }}
            historySizes={{
              right: historyPreferences.history_right_width,
              bottom: historyPreferences.history_bottom_height,
            }}
            onHistorySizeChange={(position, size) =>
              setHistoryPreferences((current) => ({
                ...current,
                [position === 'right' ? 'history_right_width' : 'history_bottom_height']: size,
              }))
            }
            onSelectSheet={(sheetId) => void selectSheet(sheetId)}
            onCopySheet={(sheetId) => void copyCurrentSheet(sheetId)}
            onRenameSheet={(sheetId) => void renameSheetById(sheetId)}
            onSetPrimarySheet={(sheetId) => void setPrimarySheet(sheetId)}
            onUnsetPrimarySheet={(sheetId) => void unsetPrimarySheet(sheetId)}
            onDeleteSheet={(sheetId) => void deleteSheetById(sheetId)}
            onImportWorkbook={(file) => void importWorkingWorkbook(file)}
            onExportCurrent={() => void exportWorkbookToExcel('current')}
            onExportAll={() => void exportWorkbookToExcel('all')}
            onComposeReport={() => void composeReportFromCurrentSheet()}
            onSaveProject={saveCurrentProject}
            onSelectCell={async (selection) => {
              if (!workbook) return
              setHistory(await api.history(workbook.id, selection.parameterKey, selection.columnKey))
            }}
            onLoadCellComment={(parameterKey, columnKey) =>
              workbook ? api.lastCellComment(workbook.id, parameterKey, columnKey) : Promise.resolve(null)
            }
            onAddComment={async (parameterKey, columnKey, comment) => {
              if (!workbook || !canWrite) return false
              try {
                await api.addCellComment(workbook.id, parameterKey, columnKey, {
                  comment,
                  expected_updated_at: expectedAt(workbook, parameterKey, columnKey),
                })
                const [nextWorkbook, nextHistory] = await Promise.all([
                  api.workbook(workbook.id),
                  api.history(workbook.id, parameterKey, columnKey),
                ])
                setWorkbook(nextWorkbook)
                setHistory(nextHistory)
                setMessage('Комментарий добавлен в историю ячейки.')
                return true
              } catch (exc) {
                await handleWriteError(exc)
                return false
              }
            }}
            onToggleUnification={async (parameterKey, columnKey, unified) => {
              if (!workbook) return
              setBusy(true)
              try {
                await api.setCellUnification(workbook.id, parameterKey, columnKey, {
                  unified,
                  expected_updated_at: expectedAt(workbook, parameterKey, columnKey),
                })
                setWorkbook(await api.workbook(workbook.id))
                setMessage(unified ? 'Ячейка отмечена как унифицированная.' : 'Унификация ячейки снята.')
              } catch (exc) {
                await handleWriteError(exc)
              } finally {
                setBusy(false)
              }
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
            onAddColumn={async (label) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.addStage(workbook.id, label)
              const next = await api.workbook(workbook.id)
              await recordHistory(previous, previousCatalog, 'Добавление столбца', 'structure', {}, next)
            }}
            onUpdateColumn={async (key, label) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.updateColumn(workbook.id, key, label)
              const next = await api.workbook(workbook.id)
              await recordHistory(previous, previousCatalog, 'Переименование столбца', 'structure', { columnKey: key }, next)
            }}
            onDeleteColumn={async (key) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              await api.deleteColumn(workbook.id, key)
              const next = await api.workbook(workbook.id)
              await recordHistory(previous, previousCatalog, 'Удаление столбца', 'structure', { columnKey: key }, next)
            }}
            onDiscard={async (parameterKey, columnKey) => {
              if (!workbook) return
              const previous = workbook
              const previousCatalog = catalog
              const updatedCell = await api.discardCell(workbook.id, parameterKey, columnKey)
              const next = workbookWithCell(previous, updatedCell)
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
              if (!workbook) return false
              try {
                const previous = workbook
                const previousCatalog = catalog
                const updatedCell = await api.patchCell(workbook.id, parameterKey, columnKey, {
                  value,
                  hyperlink,
                  expected_updated_at: expectedAt(workbook, parameterKey, columnKey),
                })
                const next = workbookWithCell(previous, updatedCell)
                await recordHistory(
                  previous,
                  previousCatalog,
                  'Ввод в ячейке',
                  'draft',
                  { parameterKey, columnKey },
                  next,
                )
                return true
              } catch (exc) {
                await handleWriteError(exc)
                return false
              }
            }}
            onConfirm={async (parameterKey, columnKey, value, comment, hyperlink) => {
              if (!workbook) return false
              try {
                const previous = workbook
                const previousCatalog = catalog
                const cell = await api.confirmCell(workbook.id, parameterKey, columnKey, {
                  value,
                  comment,
                  hyperlink,
                  expected_updated_at: expectedAt(workbook, parameterKey, columnKey),
                })
                const next = workbookWithCell(previous, cell)
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
                return true
              } catch (exc) {
                await handleWriteError(exc)
                return false
              }
            }}
          />
        ) : null}

        {tab === 'report' ? (
          <ReportTab
            workbook={workbook}
            sheets={sheetItems}
            idTableData={reportTableData}
            busy={busy}
            onExportWord={exportReportTableToWord}
            onPreview={async (sheetId) => {
              setBusy(true)
              setError('')
              try {
                const [reportWorkbook, reportCatalog] = await Promise.all([
                  api.workbook(sheetId),
                  api.catalog(sheetId),
                ])
                setReportTableData({ sheetId, workbook: reportWorkbook, catalog: reportCatalog })
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc))
              } finally {
                setBusy(false)
              }
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
