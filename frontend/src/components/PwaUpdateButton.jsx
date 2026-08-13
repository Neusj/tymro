import usePwaUpdate from '../pwa/usePwaUpdate'

export default function PwaUpdateButton() {
  const { needRefresh, updating, updateApp } = usePwaUpdate()

  if (!needRefresh) {
    return null
  }

  return (
    <button
      type="button"
      onClick={updateApp}
      disabled={updating}
      className="inline-flex min-h-11 items-center rounded-xl border border-brand-orange/70 bg-brand-orange px-3 py-2 text-sm font-semibold text-white transition hover:bg-brand-orange/90 disabled:opacity-60"
    >
      <span className="hidden sm:inline">{updating ? 'Actualizando...' : 'Actualizar'}</span>
      <span className="sm:hidden" aria-hidden="true">↻</span>
      <span className="sr-only sm:hidden">{updating ? 'Actualizando aplicación' : 'Actualizar aplicación'}</span>
    </button>
  )
}

