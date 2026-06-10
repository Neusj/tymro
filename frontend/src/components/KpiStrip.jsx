import { useState } from 'react'
import useMediaQuery from '../hooks/useMediaQuery'

/**
 * Tira de indicadores KPI.
 * - Escritorio (md+): tarjetas completas en grilla, siempre visibles.
 * - Móvil/tablet: compactas y colapsables (cerradas por defecto) para que la
 *   lista quede visible sin scroll largo.
 *
 * Props:
 *  - items: [{ label, value, hint? }]
 *  - title: etiqueta del encabezado colapsable en móvil (default "Resumen").
 *  - collapsibleOnMobile: si false, se muestran siempre (compactas) en móvil.
 */
export default function KpiStrip({ items = [], title = 'Resumen', collapsibleOnMobile = true }) {
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [open, setOpen] = useState(false)

  if (!items.length) {
    return null
  }

  // Escritorio: tarjetas completas en grilla.
  if (isDesktop) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">{item.label}</p>
            <p className="text-xl font-semibold text-brand-white">{item.value}</p>
            {item.hint ? <p className="mt-0.5 text-xs text-brand-dim">{item.hint}</p> : null}
          </div>
        ))}
      </div>
    )
  }

  // Móvil compacto (no colapsable): tira horizontal de mini-cards.
  const compactStrip = (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {items.map((item) => (
        <div key={item.label} className="min-w-[120px] flex-1 shrink-0 rounded-lg border border-brand-line bg-black/20 px-3 py-2">
          <p className="text-lg font-semibold leading-tight text-brand-white">{item.value}</p>
          <p className="truncate text-[11px] text-brand-muted">{item.label}</p>
        </div>
      ))}
    </div>
  )

  if (!collapsibleOnMobile) {
    return compactStrip
  }

  // Móvil colapsable: encabezado compacto + contenido.
  return (
    <div className="rounded-xl border border-brand-line bg-black/20">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-sm font-semibold text-brand-white"
      >
        <span className="inline-flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 3v18h18M7 14l4-4 3 3 5-6" />
          </svg>
          {title}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={`text-brand-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open ? <div className="animate-fade-rise border-t border-brand-line px-3 py-3">{compactStrip}</div> : null}
    </div>
  )
}
