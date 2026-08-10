const TYPE_STYLES = {
  success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  error: 'border-brand-red/50 bg-brand-red/10 text-red-200',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  info: 'border-brand-blue/40 bg-brand-blue/10 text-brand-white',
}

export default function FeedbackBanner({ type = 'info', title, message, onDismiss, className = '' }) {
  if (!message) {
    return null
  }

  const tone = TYPE_STYLES[type] || TYPE_STYLES.info
  const role = type === 'error' || type === 'warning' ? 'alert' : 'status'

  return (
    <div
      role={role}
      aria-live={role === 'alert' ? 'assertive' : 'polite'}
      className={`flex items-start justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${tone} ${className}`.trim()}
    >
      <div className="min-w-0">
        {title ? <p className="font-semibold text-brand-white">{title}</p> : null}
        <p className={title ? 'mt-0.5' : ''}>{message}</p>
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Cerrar mensaje"
          className="shrink-0 rounded-md border border-current/30 px-2 py-0.5 text-xs font-semibold opacity-80 transition hover:opacity-100"
        >
          Cerrar
        </button>
      ) : null}
    </div>
  )
}
