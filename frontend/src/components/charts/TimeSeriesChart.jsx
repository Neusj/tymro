import { useState } from 'react'
import { toneFor } from './chartTones'

// Gráfico de líneas para evolución temporal (ingresos, ocupación). SVG a mano: sin
// recharts/chart.js (el proyecto no tiene librería de gráficos y es una PWA donde el peso
// del bundle importa — ver frontend/CLAUDE.md).
//
// Responsivo POR CONSTRUCCIÓN: viewBox fijo (coordenadas internas) + `preserveAspectRatio="none"`
// + una clase Tailwind de alto (`h-56`, un alto de layout normal, no un `style` con px que
// pueda desbordar). El navegador estira el viewBox al tamaño real del contenedor — no hay
// medición en JS (getBoundingClientRect devuelve 0 en jsdom, así que cualquier cálculo de
// tamaño basado en DOM real habría roto los tests; acá todo el layout sale de porcentajes
// dentro del propio viewBox).
//
// Tolerancia a datos degenerados (requisito explícito): con 0 puntos o todos los valores en
// null/undefined se muestra el estado vacío; con 1 solo punto no se dibuja una línea (un
// <path> de un solo comando M no pinta nada) sino un punto + su valor; con todos los valores
// en 0 el dominio se fuerza a [0,1] para no dividir por cero.
const WIDTH = 600
const HEIGHT = 220
const PAD_LEFT = 46
const PAD_RIGHT = 12
const PAD_TOP = 14
const PAD_BOTTOM = 26
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM
const MAX_X_LABELS = 6

function niceTicks(min, max, count = 4) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return [min]
  }
  const step = (max - min) / count
  return Array.from({ length: count + 1 }, (_, index) => min + step * index)
}

export default function TimeSeriesChart({
  data = [],
  series = [],
  formatValue = (value) => String(Math.round(value)),
  formatBucket = (bucket) => bucket,
  emptyLabel = 'Sin datos en el período.',
  title,
  // Override opcional del rango del eje Y (ej. ocupación: fijar [0,100] para que el eje no
  // se "acerque" a rangos angostos y exagere variaciones chicas). Sin esto, el dominio sale
  // de los valores reales (con 0 siempre incluido).
  yDomain,
}) {
  const [hovered, setHovered] = useState(null)

  const points = Array.isArray(data) ? data : []
  const activeSeries = Array.isArray(series) ? series.filter((item) => item?.key) : []

  const hasAnyValue = points.some((point) =>
    activeSeries.some((item) => Number.isFinite(Number(point?.[item.key]))),
  )

  if (activeSeries.length === 0 || points.length === 0 || !hasAnyValue) {
    return (
      <div className="flex h-56 items-center justify-center rounded-xl border border-dashed border-brand-line bg-brand-soft/40 text-sm text-brand-muted">
        {emptyLabel}
      </div>
    )
  }

  const values = points.flatMap((point) => activeSeries.map((item) => Number(point?.[item.key]) || 0))
  let min = yDomain ? yDomain[0] : Math.min(0, ...values)
  let max = yDomain ? yDomain[1] : Math.max(0, ...values)
  if (min === max) {
    max = min + 1
  }

  const xFor = (index) => {
    if (points.length <= 1) {
      return PAD_LEFT + PLOT_W / 2
    }
    return PAD_LEFT + (index / (points.length - 1)) * PLOT_W
  }
  const yFor = (value) => PAD_TOP + PLOT_H - ((value - min) / (max - min)) * PLOT_H

  const yTicks = niceTicks(min, max, 4)
  const labelStep = Math.max(1, Math.ceil(points.length / MAX_X_LABELS))
  const singlePoint = points.length === 1

  const hoveredPoint = hovered ? points[hovered.index] : null
  const hoveredSeries = hovered ? activeSeries.find((item) => item.key === hovered.key) : null

  return (
    <div className="space-y-2">
      {/* Sin aria-hidden en el <svg>: adentro hay círculos con tabIndex real (los hit
          targets del hover/foco) — ocultarlo a lectores de pantalla mientras sigue siendo
          alcanzable por teclado es el anti-patrón que rompe la navegación, no una mejora. */}
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" className="h-56 w-full">
        {title ? <title>{title}</title> : null}

        {/* Gridlines + ticks del eje Y (recesivos, hairline) */}
        {yTicks.map((tick, index) => {
          const y = yFor(tick)
          return (
            <g key={`tick-${index}`}>
              <line x1={PAD_LEFT} x2={WIDTH - PAD_RIGHT} y1={y} y2={y} className="stroke-brand-line" strokeWidth="1" />
              <text x={PAD_LEFT - 8} y={y} textAnchor="end" dominantBaseline="middle" className="fill-brand-dim text-[9px]">
                {formatValue(tick)}
              </text>
            </g>
          )
        })}

        {/* Wash de área bajo la línea, solo para una serie única (evita ensuciar el multi-línea) */}
        {activeSeries.length === 1 && !singlePoint
          ? (() => {
              const item = activeSeries[0]
              const tone = toneFor(item.tone)
              const baseline = yFor(min)
              const areaPath = [
                `M ${xFor(0)} ${baseline}`,
                ...points.map((point, index) => `L ${xFor(index)} ${yFor(Number(point?.[item.key]) || 0)}`),
                `L ${xFor(points.length - 1)} ${baseline}`,
                'Z',
              ].join(' ')
              return <path d={areaPath} className={tone.fill} opacity="0.1" />
            })()
          : null}

        {/* Líneas */}
        {activeSeries.map((item) => {
          const tone = toneFor(item.tone)
          if (singlePoint) {
            return null
          }
          const path = points
            .map((point, index) => `${index === 0 ? 'M' : 'L'} ${xFor(index)} ${yFor(Number(point?.[item.key]) || 0)}`)
            .join(' ')
          return (
            <path
              key={item.key}
              d={path}
              fill="none"
              className={tone.stroke}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )
        })}

        {/* Puntos + hit targets (más grandes que la marca visible, según buenas prácticas de
            interacción: el círculo transparente es lo que responde al hover/foco). */}
        {activeSeries.map((item) => {
          const tone = toneFor(item.tone)
          return points.map((point, index) => {
            const value = Number(point?.[item.key]) || 0
            const cx = xFor(index)
            const cy = yFor(value)
            const isHovered = hovered?.key === item.key && hovered?.index === index
            const label = `${item.label} · ${formatBucket(point?.bucket)}: ${formatValue(value)}`
            return (
              <g key={`${item.key}-${index}`}>
                <circle
                  cx={cx}
                  cy={cy}
                  r={isHovered ? 6 : 4}
                  className={`${tone.fill} stroke-brand-ink transition-[r]`}
                  strokeWidth="2"
                />
                <circle
                  cx={cx}
                  cy={cy}
                  r="12"
                  fill="transparent"
                  tabIndex={0}
                  role="img"
                  aria-label={label}
                  className="cursor-pointer outline-none"
                  onMouseEnter={() => setHovered({ key: item.key, index })}
                  onMouseLeave={() => setHovered((prev) => (prev?.key === item.key && prev?.index === index ? null : prev))}
                  onFocus={() => setHovered({ key: item.key, index })}
                  onBlur={() => setHovered((prev) => (prev?.key === item.key && prev?.index === index ? null : prev))}
                >
                  <title>{label}</title>
                </circle>
              </g>
            )
          })
        })}

        {/* Etiquetas del eje X: muestreadas para no superponerse */}
        {points.map((point, index) => {
          const isEdge = index === 0 || index === points.length - 1
          if (!isEdge && index % labelStep !== 0) {
            return null
          }
          return (
            <text
              key={`x-${index}`}
              x={xFor(index)}
              y={HEIGHT - 8}
              textAnchor="middle"
              className="fill-brand-dim text-[9px]"
            >
              {formatBucket(point?.bucket)}
            </text>
          )
        })}
      </svg>

      {/* Leyenda: obligatoria desde 2 series; con 1 sola no hace falta (el título ya la nombra) */}
      {activeSeries.length > 1 ? (
        <div className="flex flex-wrap gap-3 text-xs text-brand-muted">
          {activeSeries.map((item) => (
            <span key={item.key} className="inline-flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${toneFor(item.tone).dot}`} aria-hidden="true" />
              {item.label}
            </span>
          ))}
        </div>
      ) : null}

      {/* Lectura accesible del punto con foco/hover: mismo dato que el <title> nativo, pero
          visible sin depender del mouse (teclado, touch, o simplemente lectura directa). */}
      <p className="min-h-[1rem] text-xs text-brand-muted" aria-live="polite">
        {hoveredPoint && hoveredSeries
          ? `${hoveredSeries.label} · ${formatBucket(hoveredPoint.bucket)}: ${formatValue(Number(hoveredPoint[hoveredSeries.key]) || 0)}`
          : ''}
      </p>
    </div>
  )
}
