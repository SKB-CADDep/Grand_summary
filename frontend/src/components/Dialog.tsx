import type { ReactNode } from 'react'

type Props = {
  title: string
  children: ReactNode
  onClose: () => void
  actions?: ReactNode
  wide?: boolean
}

export function Dialog({ title, children, onClose, actions, wide }: Props) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className={`modal${wide ? ' wide' : ''}`} onClick={(event) => event.stopPropagation()}>
        <h2>{title}</h2>
        <div className="body">{children}</div>
        <div className="actions">
          {actions}
          <button type="button" className="win-btn" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  )
}
