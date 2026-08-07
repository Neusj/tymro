import { useMemo, useState } from 'react'

const DAY_MS = 24 * 60 * 60 * 1000

export function toIsoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function todayIsoDate() {
  return toIsoDate(new Date())
}

function dateFromIso(value) {
  const [year, month, day] = String(value).split('-').map(Number)
  return new Date(year, month - 1, day)
}

function addDays(value, days) {
  return new Date(dateFromIso(value).getTime() + days * DAY_MS)
}

function mondayOfWeek(value) {
  const date = dateFromIso(value)
  const day = date.getDay()
  const offset = day === 0 ? -6 : 1 - day
  return new Date(date.getTime() + offset * DAY_MS)
}

function formatLongDate(value) {
  return dateFromIso(value).toLocaleDateString('es-CL', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function formatDayButton(value) {
  const date = dateFromIso(value)
  const weekday = date.toLocaleDateString('es-CL', { weekday: 'short' }).replace('.', '')
  return {
    weekday,
    day: date.toLocaleDateString('es-CL', { day: '2-digit' }),
    month: date.toLocaleDateString('es-CL', { month: 'short' }).replace('.', ''),
  }
}

export default function DaySelector({ value, onChange, className = '' }) {
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [draftDate, setDraftDate] = useState(value)

  const weekDays = useMemo(() => {
    const monday = mondayOfWeek(value)
    return Array.from({ length: 7 }, (_, index) => toIsoDate(new Date(monday.getTime() + index * DAY_MS)))
  }, [value])

  const moveWeek = (days) => {
    onChange(toIsoDate(addDays(value, days)))
  }

  return (
    <section className={`card-surface space-y-3 p-4 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="panel-title">Agenda por dia</h2>
          <p className="text-xs text-brand-muted">{formatLongDate(value)}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="Semana anterior"
            onClick={() => moveWeek(-7)}
            className="grid h-9 w-9 place-items-center rounded-lg border border-brand-line text-brand-white transition hover:border-brand-blue"
          >
            &lt;
          </button>
          <button
            type="button"
            aria-label="Semana siguiente"
            onClick={() => moveWeek(7)}
            className="grid h-9 w-9 place-items-center rounded-lg border border-brand-line text-brand-white transition hover:border-brand-blue"
          >
            &gt;
          </button>
          <button
            type="button"
            onClick={() => {
              setDraftDate(value)
              setCalendarOpen((open) => !open)
            }}
            className="rounded-lg border border-brand-blue px-3 py-2 text-xs font-semibold text-brand-white"
          >
            Calendario
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-2">
        {weekDays.map((item) => {
          const selected = item === value
          const label = formatDayButton(item)
          return (
            <button
              key={item}
              type="button"
              aria-label={`Seleccionar ${item}`}
              aria-pressed={selected}
              onClick={() => onChange(item)}
              className={`min-h-16 rounded-lg border px-2 py-2 text-center transition ${
                selected
                  ? 'border-brand-blue bg-brand-blue/20 text-brand-white'
                  : 'border-brand-line bg-black/20 text-brand-muted hover:border-brand-blue hover:text-brand-white'
              }`}
            >
              <span className="block text-[11px] font-semibold uppercase">{label.weekday}</span>
              <span className="block text-lg font-semibold leading-tight">{label.day}</span>
              <span className="block text-[11px] uppercase">{label.month}</span>
            </button>
          )
        })}
      </div>

      {calendarOpen ? (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-brand-line bg-black/20 p-3">
          <label className="space-y-1 text-xs text-brand-muted">
            <span>Fecha</span>
            <input
              type="date"
              aria-label="Fecha del calendario"
              value={draftDate}
              onChange={(event) => setDraftDate(event.target.value)}
              className="block rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              if (draftDate) {
                onChange(draftDate)
                setCalendarOpen(false)
              }
            }}
            className="rounded-lg bg-brand-blue px-3 py-2 text-xs font-semibold text-white"
          >
            Aplicar fecha
          </button>
        </div>
      ) : null}
    </section>
  )
}
