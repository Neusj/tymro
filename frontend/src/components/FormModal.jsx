import { useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import useBodyScrollLock from '../hooks/useBodyScrollLock'
import useModalFocus, { getFocusable } from '../hooks/useModalFocus'

export default function FormModal({ open, title, children, onClose, closeDisabled = false, size = 'md', variant = 'modal' }) {
  useBodyScrollLock(open)
  const titleId = useId()
  const dialogRef = useRef(null)
  const bodyRef = useRef(null)

  const close = () => {
    if (!closeDisabled) {
      onClose?.()
    }
  }

  useModalFocus({
    open,
    containerRef: dialogRef,
    getInitialFocus: () => getFocusable(bodyRef.current)[0],
    onEscape: close,
    escapeDisabled: closeDisabled,
  })

  if (!open || typeof document === 'undefined') {
    return null
  }

  const widthClass = size === 'lg' ? 'sm:max-w-3xl' : 'sm:max-w-lg'
  const isDrawer = variant === 'drawer'

  return createPortal(
    <div
      className={`fixed inset-0 z-40 flex overflow-y-auto bg-black/75 backdrop-blur-sm ${isDrawer ? 'items-stretch justify-end p-0 sm:p-3' : 'items-center justify-center p-4'}`}
      onClick={close}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className={`flex w-full flex-col overflow-hidden border border-brand-line bg-brand-soft shadow-float ${
          isDrawer
            ? 'h-full max-w-3xl rounded-none animate-slide-up sm:h-auto sm:max-h-full sm:rounded-2xl'
            : `max-h-[85vh] rounded-2xl animate-scale-in ${widthClass}`
        }`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-brand-line bg-brand-soft/95 px-5 py-4 backdrop-blur">
          <h3 id={titleId} className="font-display text-lg font-semibold text-brand-white">{title}</h3>
          <button
            type="button"
            onClick={close}
            disabled={closeDisabled}
            aria-label="Cerrar"
            className="inline-flex min-h-9 items-center rounded-lg border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:border-brand-blue hover:text-brand-white disabled:opacity-60"
          >
            Cerrar
          </button>
        </div>
        <div ref={bodyRef} className="overflow-y-auto px-5 py-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
