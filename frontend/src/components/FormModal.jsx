import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import useBodyScrollLock from '../hooks/useBodyScrollLock'

export default function FormModal({ open, title, children, onClose }) {
  useBodyScrollLock(open)

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose?.()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  if (!open || typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto bg-black/75 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="flex max-h-[85vh] w-full flex-col overflow-hidden rounded-2xl border border-brand-line bg-brand-soft shadow-float animate-scale-in sm:max-w-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-brand-line bg-brand-soft/95 px-5 py-4 backdrop-blur">
          <h3 className="font-display text-lg font-semibold text-brand-white">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="inline-flex min-h-9 items-center rounded-lg border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:border-brand-blue hover:text-brand-white"
          >
            Cerrar
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
