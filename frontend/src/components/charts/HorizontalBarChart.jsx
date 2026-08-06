import { useState } from 'react'
import { toneFor } from './chartTones'

// Gráfico de barras horizontales para el desglose por categoría (por método, por
// disciplina, por hora). El texto (etiqueta, valor) es HTML normal — así se trunca con
// CSS y no rompe con nombres largos de disciplina — pero la MARCA de dato (la barra) es
// SVG inline de verdad: un <rect> dentro de un viewBox fijo "0 0 100 10", con el ancho
// como PORCENTAJE del máximo. Cada fila crece con `w-full`/`flex-1`: nada depende de un
// alto en px medido en JS, así que no hay riesgo de desborde ni de reventar en jsdom.
//
// `items`: [{ label, value, hint?, tone? }]. `tone` por fila es opcional: por default
// todas las barras comparten el mismo tono (una sola serie categórica-nominal — "método A"
// vs "método B" son categorías de la MISMA métrica, no series distintas), pero una página
// puede pisarlo por fila cuando esa categoría ya tiene un color propio en otro gráfico de
// la misma pantalla (ej. efectivo/transferencia).
export default function HorizontalBarChart({
  items = [],
  formatValue = (value) => String(Math.round(value)),
  emptyLabel = 'Sin datos en el período.',
  tone = 'orange',
}) {
  const [hovered, setHovered] = useState(null)

  const rows = Array.isArray(items) ? items.filter((item) => item && item.label != null) : []

  if (rows.length === 0) {
    return (
      <div className="flex h-20 items-center justify-center rounded-xl border border-dashed border-brand-line bg-brand-soft/40 text-sm text-brand-muted">
        {emptyLabel}
      </div>
    )
  }

  const max = Math.max(1, ...rows.map((row) => Math.abs(Number(row.value) || 0)))
  const hoveredRow = hovered !== null ? rows[hovered] : null

  return (
    <div className="space-y-2.5">
      {rows.map((row, index) => {
        const value = Number(row.value) || 0
        const pct = Math.max(0, Math.min(100, (Math.abs(value) / max) * 100))
        const rowTone = toneFor(row.tone || tone)
        const label = `${row.label}: ${formatValue(value)}${row.hint ? ` · ${row.hint}` : ''}`
        return (
          <div key={row.key ?? row.label ?? index} className="flex items-center gap-3 text-sm">
            <span className="w-28 shrink-0 truncate text-brand-muted sm:w-36" title={row.label}>
              {row.label}
            </span>
            <svg
              viewBox="0 0 100 10"
              preserveAspectRatio="none"
              className="h-2.5 flex-1 overflow-hidden rounded-full bg-black/30"
              tabIndex={0}
              role="img"
              aria-label={label}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered((prev) => (prev === index ? null : prev))}
              onFocus={() => setHovered(index)}
              onBlur={() => setHovered((prev) => (prev === index ? null : prev))}
            >
              <title>{label}</title>
              <rect x="0" y="0" width={pct} height="10" className={rowTone.fill} />
            </svg>
            <span className="w-20 shrink-0 text-right font-medium tabular-nums text-brand-white sm:w-24">
              {formatValue(value)}
            </span>
          </div>
        )
      })}

      <p className="min-h-[1rem] text-xs text-brand-muted" aria-live="polite">
        {hoveredRow ? `${hoveredRow.label}: ${formatValue(Number(hoveredRow.value) || 0)}${hoveredRow.hint ? ` · ${hoveredRow.hint}` : ''}` : ''}
      </p>
    </div>
  )
}
