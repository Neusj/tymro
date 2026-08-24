import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { registrationApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const TRIAL_RESULT_LIMIT = 10

const dateFormatter = new Intl.DateTimeFormat('es-CL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  hour: '2-digit',
  minute: '2-digit',
})

const timeFormatter = new Intl.DateTimeFormat('es-CL', {
  hour: '2-digit',
  minute: '2-digit',
})

const shortDayFormatter = new Intl.DateTimeFormat('es-CL', {
  weekday: 'short',
  day: 'numeric',
})

function formatWhen(value) {
  try {
    return dateFormatter.format(new Date(value))
  } catch {
    return value
  }
}

function formatTime(value) {
  try {
    return timeFormatter.format(new Date(value))
  } catch {
    return value
  }
}

function localDateKey(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function buildDayOptions() {
  const today = new Date()
  return Array.from({ length: 5 }, (_, index) => {
    const date = new Date(today)
    date.setDate(today.getDate() + index)
    const label = index === 0
      ? 'Hoy'
      : index === 1
        ? 'Mañana'
        : shortDayFormatter.format(date).replace('.', '')
    return {
      value: localDateKey(date),
      label,
    }
  })
}

function normalizeTrialPayload(data) {
  if (Array.isArray(data)) {
    return {
      results: data,
      count: data.length,
      limit: TRIAL_RESULT_LIMIT,
      has_more: false,
      filters: { branches: [], disciplines: [], teachers: [] },
    }
  }
  return {
    results: Array.isArray(data?.results) ? data.results : [],
    count: Number.isFinite(data?.count) ? data.count : 0,
    limit: Number.isFinite(data?.limit) ? data.limit : TRIAL_RESULT_LIMIT,
    has_more: Boolean(data?.has_more),
    filters: {
      branches: Array.isArray(data?.filters?.branches) ? data.filters.branches : [],
      disciplines: Array.isArray(data?.filters?.disciplines) ? data.filters.disciplines : [],
      teachers: Array.isArray(data?.filters?.teachers) ? data.filters.teachers : [],
    },
  }
}

export default function TrialBookingPage() {
  const { user, logout, refreshMe } = useAuth()
  const navigate = useNavigate()
  const dayOptions = useMemo(buildDayOptions, [])
  const [selectedDate, setSelectedDate] = useState(dayOptions[0]?.value || localDateKey(new Date()))
  const [classes, setClasses] = useState([])
  const [filterOptions, setFilterOptions] = useState({ branches: [], disciplines: [], teachers: [] })
  const [totalCount, setTotalCount] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [bookingId, setBookingId] = useState(null)
  const [booked, setBooked] = useState(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [disciplineId, setDisciplineId] = useState('')
  const [branchId, setBranchId] = useState('')
  const canUseTrial = user?.role === 'student' && user?.trial_eligible && !user?.has_used_trial

  const brandStyle = useMemo(
    () => ({
      '--dynamic-primary': user?.organization_detail?.primary_color || '#dc2626',
      '--dynamic-secondary': user?.organization_detail?.secondary_color || '#2563eb',
    }),
    [user],
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim())
    }, 300)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    setDisciplineId('')
    setBranchId('')
    setSearch('')
    setDebouncedSearch('')
  }, [selectedDate])

  useEffect(() => {
    let active = true
    const load = async () => {
      setError('')
      if (user && !canUseTrial) {
        setClasses([])
        setFilterOptions({ branches: [], disciplines: [], teachers: [] })
        setTotalCount(0)
        setHasMore(false)
        setLoading(false)
        return
      }

      setLoading(true)
      try {
        const payload = normalizeTrialPayload(await registrationApi.listTrialClasses({
          date: selectedDate,
          q: debouncedSearch || undefined,
          discipline_id: disciplineId || undefined,
          branch_id: branchId || undefined,
          limit: TRIAL_RESULT_LIMIT,
          include_filters: 1,
        }))
        if (active) {
          setClasses(payload.results)
          setFilterOptions(payload.filters)
          setTotalCount(payload.count)
          setHasMore(payload.has_more)
        }
      } catch {
        if (active) {
          setClasses([])
          setTotalCount(0)
          setHasMore(false)
          setError('No se pudieron cargar las clases de prueba.')
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }
    load()
    return () => {
      active = false
    }
  }, [branchId, canUseTrial, debouncedSearch, disciplineId, selectedDate, user])

  const hasFilters = Boolean(search.trim() || disciplineId || branchId)
  const showBranchFilter = filterOptions.branches.length > 1

  const clearFilters = () => {
    setSearch('')
    setDebouncedSearch('')
    setDisciplineId('')
    setBranchId('')
  }

  const book = async (gymClass) => {
    setError('')
    setBookingId(gymClass.id)
    try {
      await registrationApi.bookTrial(gymClass.id)
      setBooked(gymClass)
      // La reserva marco has_used_trial=true en el backend. Refrescamos la sesion
      // para que TrialClassBanner desaparezca al volver a la app.
      refreshMe().catch(() => {})
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo reservar la clase. Prueba con otra.')
    } finally {
      setBookingId(null)
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-brand-black px-4 py-6 text-brand-white sm:py-8" style={brandStyle}>
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(circle at 15% 10%, color-mix(in srgb, var(--dynamic-primary) 24%, transparent), transparent 30%),' +
            'radial-gradient(circle at 85% 8%, color-mix(in srgb, var(--dynamic-secondary) 22%, transparent), transparent 28%)',
        }}
      />

      <main className="relative z-10 mx-auto w-full max-w-2xl">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-display text-xs font-bold uppercase tracking-[0.24em] text-brand-orange">
              {user?.organization_detail?.name || 'TYMRO'}
            </p>
            <h1 className="mt-1 font-display text-2xl font-bold sm:text-3xl">
              {canUseTrial ? 'Tu clase de prueba gratis' : 'Clase de prueba no disponible'}
            </h1>
          </div>
          <button
            type="button"
            onClick={logout}
            className="inline-flex min-h-9 shrink-0 items-center rounded-lg border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:border-brand-orange hover:text-brand-white"
          >
            Salir
          </button>
        </header>

        {booked ? (
          <section className="mt-8 rounded-2xl border border-brand-line bg-brand-soft/95 p-7 text-center shadow-glow animate-scale-in">
            <div
              className="mx-auto flex h-14 w-14 items-center justify-center rounded-full text-2xl"
              style={{ background: 'color-mix(in srgb, var(--dynamic-secondary) 22%, transparent)' }}
              aria-hidden="true"
            >
              OK
            </div>
            <h2 className="mt-4 font-display text-xl font-bold">Reserva confirmada</h2>
            <p className="mt-2 text-sm text-brand-muted">
              Te esperamos en <span className="font-semibold text-brand-white">{booked.name}</span>
              <br />
              {formatWhen(booked.start_datetime)}
            </p>
            <button
              type="button"
              onClick={() => navigate('/student/classes/reservations', { replace: true })}
              className="mt-6 inline-flex min-h-11 items-center rounded-xl px-5 py-2 text-sm font-semibold text-white transition hover:brightness-110"
              style={{ background: 'linear-gradient(to right, var(--dynamic-primary), var(--dynamic-secondary))' }}
            >
              Ver mis reservas
            </button>
          </section>
        ) : !canUseTrial ? (
          <section className="mt-8 rounded-2xl border border-brand-line bg-brand-soft/80 p-6 text-center text-sm text-brand-muted">
            Esta cuenta no tiene una clase de prueba gratis disponible.
          </section>
        ) : (
          <>
            <p className="mt-2 text-sm text-brand-muted">Elige la clase y el día que te sirve. Solo puedes tomar una clase de prueba.</p>

            {error ? (
              <p className="mt-5 rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{error}</p>
            ) : null}

            <section className="mt-6 space-y-4">
              <div className="grid grid-cols-5 gap-1.5 rounded-2xl border border-brand-line bg-brand-soft/80 p-1.5">
                {dayOptions.map((day) => {
                  const active = selectedDate === day.value
                  return (
                    <button
                      key={day.value}
                      type="button"
                      onClick={() => setSelectedDate(day.value)}
                      className={`min-h-11 rounded-xl px-1 text-center text-xs font-semibold transition ${
                        active ? 'text-white shadow-soft' : 'text-brand-muted hover:bg-brand-line/50 hover:text-brand-white'
                      }`}
                      style={active ? { background: 'linear-gradient(to right, var(--dynamic-primary), var(--dynamic-secondary))' } : undefined}
                      aria-pressed={active}
                    >
                      {day.label}
                    </button>
                  )
                })}
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                <label className="block">
                  <span className="sr-only">Buscar clase</span>
                  <input
                    type="search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Buscar por clase, profe o sede"
                    className="min-h-11 w-full rounded-xl border border-brand-line bg-brand-soft/90 px-3 text-sm text-brand-white outline-none transition placeholder:text-brand-dim focus:border-brand-orange"
                  />
                </label>

                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <label className="block">
                    <span className="sr-only">Disciplina</span>
                    <select
                      value={disciplineId}
                      onChange={(event) => setDisciplineId(event.target.value)}
                      className="min-h-11 w-full rounded-xl border border-brand-line bg-brand-soft/90 px-3 text-sm text-brand-white outline-none transition focus:border-brand-orange"
                    >
                      <option value="">Todas las disciplinas</option>
                      {filterOptions.disciplines.map((option) => (
                        <option key={option.id} value={option.id}>{option.name}</option>
                      ))}
                    </select>
                  </label>

                  {showBranchFilter ? (
                    <label className="block">
                      <span className="sr-only">Sucursal</span>
                      <select
                        value={branchId}
                        onChange={(event) => setBranchId(event.target.value)}
                        className="min-h-11 w-full rounded-xl border border-brand-line bg-brand-soft/90 px-3 text-sm text-brand-white outline-none transition focus:border-brand-orange"
                      >
                        <option value="">Todas las sedes</option>
                        {filterOptions.branches.map((option) => (
                          <option key={option.id} value={option.id}>{option.name}</option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                </div>
              </div>
            </section>

            {loading ? (
              <div className="mt-8 rounded-2xl border border-brand-line bg-brand-soft/80 p-5 text-sm text-brand-muted">
                Cargando clases...
              </div>
            ) : classes.length === 0 ? (
              <div className="mt-8 rounded-2xl border border-brand-line bg-brand-soft/80 p-6 text-center text-sm text-brand-muted">
                <p>{hasFilters ? 'No hay resultados para esa búsqueda.' : 'No hay clases de prueba disponibles para ese día.'}</p>
                {hasFilters ? (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="mt-4 inline-flex min-h-10 items-center rounded-xl border border-brand-line px-4 text-sm font-semibold text-brand-white transition hover:border-brand-orange"
                  >
                    Limpiar filtros
                  </button>
                ) : null}
              </div>
            ) : (
              <>
                <ul className="mt-6 space-y-3">
                  {classes.map((gymClass) => {
                    const title = gymClass.discipline_name || gymClass.class_type_name || gymClass.name
                    return (
                      <li
                        key={gymClass.id}
                        className="rounded-2xl border border-brand-line bg-brand-soft/85 p-4 shadow-soft"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-display text-xl font-bold text-brand-white">{formatTime(gymClass.start_datetime)}</p>
                            <p className="mt-1 truncate font-semibold text-brand-white">{title}</p>
                            {title !== gymClass.name ? (
                              <p className="mt-0.5 truncate text-xs text-brand-muted">{gymClass.name}</p>
                            ) : null}
                          </div>
                          <span className="shrink-0 rounded-full border border-brand-line px-2.5 py-1 text-xs font-semibold text-brand-muted">
                            {gymClass.seats_left} cupos
                          </span>
                        </div>

                        <div className="mt-3 grid gap-1 text-xs text-brand-muted">
                          <p className="truncate">{gymClass.teacher_name || 'Profesor por confirmar'}</p>
                          <p className="truncate">{gymClass.branch_name || 'Sucursal por confirmar'}</p>
                        </div>

                        <button
                          type="button"
                          onClick={() => book(gymClass)}
                          disabled={bookingId === gymClass.id}
                          className="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                          style={{ background: 'linear-gradient(to right, var(--dynamic-primary), var(--dynamic-secondary))' }}
                        >
                          {bookingId === gymClass.id ? 'Reservando...' : 'Reservar esta clase'}
                        </button>
                      </li>
                    )
                  })}
                </ul>

                {hasMore ? (
                  <div className="mt-4 rounded-2xl border border-brand-line bg-brand-soft/70 p-4 text-center text-sm text-brand-muted">
                    Mostrando {TRIAL_RESULT_LIMIT} de {totalCount}. Usa búsqueda o filtros para afinar.
                  </div>
                ) : null}
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
