import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import useBodyScrollLock from '../hooks/useBodyScrollLock'
import useModalFocus from '../hooks/useModalFocus'
import FeedbackBanner from './FeedbackBanner'

const VARIANT_STYLES = {
  default: 'bg-brand-blue text-white hover:brightness-110',
  danger: 'bg-brand-red text-white hover:brightness-110',
  warning: 'bg-brand-orange text-brand-black hover:brightness-110',
}

export default function ConfirmWithReasonDialog({
  open,
  title,
  description,
  message,
  reasonLabel = 'Motivo',
  placeholder = '',
  reasonRequired = true,
  confirmLabel = 'Confirmar',
  cancelLabel = 'Cancelar',
  variant = 'warning',
  loading = false,
  error,
  onConfirm,
  onCancel,
}) {
  useBodyScrollLock(open)
  const titleId = useId()
  const descriptionId = useId()
  const reasonId = useId()
  const dialogRef = useRef(null)
  const reasonRef = useRef(null)
  const [reason, setReason] = useState('')
  const [localError, setLocalError] = useState('')
  const resolvedMessage = message ?? description
  const confirmClass = VARIANT_STYLES[variant] || VARIANT_STYLES.default

  useEffect(() => {
    if (!open) {
      return
    }
    setReason('')
    setLocalError('')
  }, [open])

  useModalFocus({
    open,
    containerRef: dialogRef,
    initialFocusRef: reasonRef,
    onEscape: onCancel,
    escapeDisabled: loading,
  })

  if (!open || typeof document === 'undefined') {
    return null
  }

  const submit = (event) => {
    event.preventDefault()
    const trimmed = reason.trim()
    if (reasonRequired && !trimmed) {
      setLocalError('Ingresa un motivo para continuar.')
      return
    }
    setLocalError('')
    onConfirm?.(trimmed)
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
      <form
        ref={dialogRef}
        tabIndex={-1}
        onSubmit={submit}
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-brand-line bg-brand-soft shadow-glow animate-scale-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="space-y-4 overflow-y-auto p-5">
          <div>
            <h3 id={titleId} className="text-lg font-semibold">{title}</h3>
            {resolvedMessage ? <p id={descriptionId} className="mt-2 text-sm text-brand-muted">{resolvedMessage}</p> : null}
          </div>

          <label htmlFor={reasonId} className="block space-y-1 text-sm">
            <span>{reasonLabel}{reasonRequired ? <span className="text-brand-red"> *</span> : null}</span>
            <textarea
              ref={reasonRef}
              id={reasonId}
              rows={4}
              value={reason}
              onChange={(event) => {
                setReason(event.target.value)
                if (localError) {
                  setLocalError('')
                }
              }}
              placeholder={placeholder}
              disabled={loading}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white placeholder:text-brand-dim disabled:opacity-60"
            />
          </label>

          <FeedbackBanner type="error" message={error || localError} />
        </div>

        <div className="flex justify-end gap-2 border-t border-brand-line px-5 py-4">
          <button
            type="button"
            disabled={loading}
            onClick={onCancel}
            className="rounded-xl border border-brand-line px-4 py-2 text-sm text-brand-muted transition hover:border-brand-orange hover:text-brand-white disabled:opacity-60"
          >
            {cancelLabel}
          </button>
          <button
            type="submit"
            disabled={loading}
            className={`rounded-xl px-4 py-2 text-sm font-semibold transition disabled:opacity-60 ${confirmClass}`}
          >
            {loading ? 'Procesando...' : confirmLabel}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  )
}
