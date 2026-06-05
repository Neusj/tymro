export default function FormModal({ open, title, children, onClose }) {
  if (!open) {
    return null
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl border border-brand-line bg-brand-soft shadow-float animate-scale-in sm:max-w-2xl sm:rounded-2xl"
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
    </div>
  )
}
