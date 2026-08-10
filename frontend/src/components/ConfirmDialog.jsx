import { useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import useBodyScrollLock from '../hooks/useBodyScrollLock'
import useModalFocus from '../hooks/useModalFocus'

const VARIANT_STYLES = {
  default: {
    confirm: 'bg-brand-blue text-white hover:brightness-110',
  },
  danger: {
    confirm: 'bg-brand-red text-white hover:brightness-110',
  },
  warning: {
    confirm: 'bg-brand-orange text-brand-black hover:brightness-110',
  },
}

export default function ConfirmDialog({
  open,
  title,
  description,
  message,
  confirmLabel = 'Confirmar',
  cancelLabel = 'Cancelar',
  variant = 'danger',
  onConfirm,
  onCancel,
  loading = false,
  confirmDisabled = false,
  children,
}) {
  useBodyScrollLock(open)
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef(null)
  const confirmButtonRef = useRef(null)
  const cancelButtonRef = useRef(null)
  const resolvedMessage = message ?? description
  const styles = VARIANT_STYLES[variant] || VARIANT_STYLES.default

  useModalFocus({
    open,
    containerRef: dialogRef,
    getInitialFocus: () => {
      const target = variant === 'danger' ? cancelButtonRef.current : confirmButtonRef.current
      if (target && !target.disabled) {
        return target
      }
      return cancelButtonRef.current
    },
    onEscape: onCancel,
    escapeDisabled: loading,
  })

  if (!open || typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/80 p-4"
      onClick={loading ? undefined : onCancel}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={resolvedMessage ? descriptionId : undefined}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-brand-line bg-brand-soft shadow-glow animate-scale-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="overflow-y-auto p-5">
          <h3 id={titleId} className="text-lg font-semibold">{title}</h3>
          {resolvedMessage ? <p id={descriptionId} className="mt-2 text-sm text-brand-muted">{resolvedMessage}</p> : null}
          {children}
        </div>
        <div className="flex justify-end gap-2 border-t border-brand-line px-5 py-4">
          <button
            ref={cancelButtonRef}
            type="button"
            disabled={loading}
            onClick={onCancel}
            className="rounded-xl border border-brand-line px-4 py-2 text-sm text-brand-muted transition hover:border-brand-orange hover:text-brand-white disabled:opacity-60"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmButtonRef}
            type="button"
            disabled={loading || confirmDisabled}
            onClick={onConfirm}
            className={`rounded-xl px-4 py-2 text-sm font-semibold transition disabled:opacity-60 ${styles.confirm}`}
          >
            {loading ? 'Procesando...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
