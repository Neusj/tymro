import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import useBodyScrollLock from '../hooks/useBodyScrollLock'

export default function ConfirmDialog({ open, title, description, confirmLabel = 'Confirmar', onConfirm, onCancel, loading = false }) {
  useBodyScrollLock(open)

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !loading) {
        onCancel?.()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, loading, onCancel])

  if (!open || typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/80 p-4"
      onClick={loading ? undefined : onCancel}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-brand-line bg-brand-soft shadow-glow animate-scale-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="overflow-y-auto p-5">
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="mt-2 text-sm text-brand-muted">{description}</p>
        </div>
        <div className="flex justify-end gap-2 border-t border-brand-line px-5 py-4">
          <button type="button" onClick={onCancel} className="rounded-xl border border-brand-line px-4 py-2 text-sm text-brand-muted">
            Cancelar
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={onConfirm}
            className="rounded-xl bg-brand-red px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {loading ? 'Procesando...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
