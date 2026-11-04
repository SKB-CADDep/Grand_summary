import { useLayoutEffect, useMemo, useState } from 'react'
import type { GuideKind, GuideStep } from '../guide'
import { Dialog } from './Dialog'

type OverlayProps = {
  steps: GuideStep[]
  index: number
  onBack: () => void
  onNext: () => void
  onSkip: () => void
}

function placeCard(hole: DOMRect | null) {
  const width = 340
  const margin = 12
  const left = Math.min(
    Math.max(margin, (hole?.left ?? 24) + (hole && hole.left + width + 24 < window.innerWidth ? 0 : 0)),
    window.innerWidth - width - margin,
  )
  let top = (hole?.bottom ?? 48) + 12
  if (top + 220 > window.innerHeight) {
    top = Math.max(margin, (hole?.top ?? 220) - 220)
  }
  if (hole && hole.right + width + 24 < window.innerWidth) {
    return { left: Math.min(hole.right + 16, window.innerWidth - width - margin), top: Math.max(margin, hole.top) }
  }
  return { left, top }
}

export function GuideOverlay({ steps, index, onBack, onNext, onSkip }: OverlayProps) {
  const step = steps[index]
  const [hole, setHole] = useState<DOMRect | null>(null)

  useLayoutEffect(() => {
    if (!step) return
    const measure = () => {
      const node = document.querySelector(`[data-guide="${step.target}"]`)
      setHole(node ? node.getBoundingClientRect() : null)
    }
    const timer = window.setTimeout(measure, 60)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [step])

  const card = useMemo(() => placeCard(hole), [hole])
  if (!step) return null
  const last = index === steps.length - 1

  return (
    <div className="guide-layer" role="dialog" aria-label="Обучение">
      {hole ? (
        <div
          className="guide-spot"
          style={{
            top: hole.top - 6,
            left: hole.left - 6,
            width: hole.width + 12,
            height: hole.height + 12,
          }}
        />
      ) : (
        <div className="guide-dim" />
      )}
      <div className="guide-card" style={{ top: card.top, left: card.left }}>
        <div className="hint">
          Шаг {index + 1} из {steps.length}
        </div>
        <strong>{step.title}</strong>
        <p>{step.body}</p>
        <div className="toolbar">
          <button type="button" className="win-btn" disabled={index === 0} onClick={onBack}>
            Назад
          </button>
          <span style={{ flex: 1 }} />
          <button type="button" className="win-btn" onClick={onNext}>
            {last ? 'Готово' : 'Далее'}
          </button>
        </div>
        <button type="button" className="guide-skip" onClick={onSkip}>
          Пропустить обучение
        </button>
      </div>
    </div>
  )
}

type ChoiceProps = {
  onPick: (kind: GuideKind) => void
  onClose: () => void
}

export function GuideChoice({ onPick, onClose }: ChoiceProps) {
  return (
    <Dialog
      title="Обучение"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="win-btn" onClick={() => onPick('app')}>
            Обзор приложения
          </button>
          <button type="button" className="win-btn" onClick={() => onPick('table')}>
            Работа с таблицей
          </button>
        </>
      }
    >
      <p>
        Короткий тур: обведём основные элементы и кратко поясним, зачем они нужны. Обзор — вкладки и объект.
        Работа с таблицей — цвета, сохранение и отчёт.
      </p>
    </Dialog>
  )
}
