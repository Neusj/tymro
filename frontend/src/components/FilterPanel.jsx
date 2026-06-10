import { useEffect, useMemo, useState } from 'react'
import useMediaQuery from '../hooks/useMediaQuery'
import { FilterGroupContext } from './FilterDropdown'

/**
 * Panel de filtros colapsable y reutilizable.
 * - Abierto por defecto en escritorio (md+), cerrado en móvil/tablet.
 * - Cabecera siempre visible con contador de filtros activos y acción "Limpiar".
 *
 * Props:
 *  - children: controles de filtro (FilterDropdown, chips, etc.).
 *  - activeCount: nº de filtros activos (muestra badge y habilita "Limpiar").
 *  - onClear: callback para limpiar filtros.
 *  - title: etiqueta del botón (default "Filtros").
 */
export default function FilterPanel({ children, activeCount = 0, onClear, title = 'Filtros' }) {
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [open, setOpen] = useState(isDesktop)
  const [openId, setOpenId] = useState(null)
  const group = useMemo(() => ({ openId, setOpenId }), [openId])

  // Sincroniza con el breakpoint (igual que AppLayout con el sidebar).
  useEffect(() => {
    setOpen(isDesktop)
  }, [isDesktop])

  return (
    <div className="rounded-xl border border-brand-line bg-black/20">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={open}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg px-1 text-sm font-semibold text-brand-white transition hover:text-brand-orange"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 5h18M6 12h12M10 19h4" />
          </svg>
          <span>{title}</span>
          {activeCount > 0 ? (
            <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-brand-orange px-1.5 text-xs font-bold text-brand-black">
              {activeCount}
            </span>
          ) : null}
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
        {activeCount > 0 && onClear ? (
          <button
            type="button"
            onClick={onClear}
            className="min-h-10 rounded-lg border border-brand-line px-3 py-2 text-xs text-brand-muted transition hover:border-brand-orange hover:text-brand-white"
          >
            Limpiar
          </button>
        ) : null}
      </div>
      {open ? (
        <div className="animate-fade-rise border-t border-brand-line px-3 py-3">
          <FilterGroupContext.Provider value={group}>{children}</FilterGroupContext.Provider>
        </div>
      ) : null}
    </div>
  )
}
