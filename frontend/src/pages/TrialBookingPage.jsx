import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { registrationApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const dateFormatter = new Intl.DateTimeFormat('es-CL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  hour: '2-digit',
  minute: '2-digit',
})

function formatWhen(value) {
  try {
    return dateFormatter.format(new Date(value))
  } catch {
    return value
  }
}

export default function TrialBookingPage() {
  const { user, logout, refreshMe } = useAuth()
  const navigate = useNavigate()
  const [classes, setClasses] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [bookingId, setBookingId] = useState(null)
  const [booked, setBooked] = useState(null)
  const canUseTrial = user?.role === 'student' && user?.trial_eligible && !user?.has_used_trial

  const brandStyle = useMemo(
    () => ({
      '--dynamic-primary': user?.organization_detail?.primary_color || '#dc2626',
      '--dynamic-secondary': user?.organization_detail?.secondary_color || '#2563eb',
    }),
    [user],
  )

  useEffect(() => {
    let active = true
    const load = async () => {
      if (user && !canUseTrial) {
        setClasses([])
        setLoading(false)
        return
      }
      try {
        const data = await registrationApi.listTrialClasses()
        if (active) {
          setClasses(Array.isArray(data) ? data : [])
        }
      } catch {
        if (active) {
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
  }, [canUseTrial, user])

  const book = async (gymClass) => {
    setError('')
    setBookingId(gymClass.id)
    try {
      await registrationApi.bookTrial(gymClass.id)
      setBooked(gymClass)
      // La reserva marcó has_used_trial=true en el backend. Refrescamos la sesión
      // para que TrialClassBanner desaparezca al volver a la app (fire-and-forget:
      // un fallo del refresco no debe romper la confirmación ya lograda).
      refreshMe().catch(() => {})
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo reservar la clase. Prueba con otra.')
    } finally {
      setBookingId(null)
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-brand-black px-4 py-8 text-brand-white" style={brandStyle}>
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(circle at 15% 10%, color-mix(in srgb, var(--dynamic-primary) 24%, transparent), transparent 30%),' +
            'radial-gradient(circle at 85% 8%, color-mix(in srgb, var(--dynamic-secondary) 22%, transparent), transparent 28%)',
        }}
      />

      <main className="relative z-10 mx-auto w-full max-w-2xl">
        <header className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange">
              {user?.organization_detail?.name || 'TYMRO'}
            </p>
            <h1 className="mt-1 font-display text-2xl font-bold sm:text-3xl">
              {canUseTrial ? 'Tu clase de prueba gratis' : 'Clase de prueba no disponible'}
            </h1>
          </div>
          <button
            type="button"
            onClick={logout}
            className="inline-flex min-h-9 items-center rounded-lg border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:border-brand-orange hover:text-brand-white"
          >
            Salir
          </button>
        </header>

        {booked ? (
          <section className="mt-8 rounded-3xl border border-brand-line bg-brand-soft/95 p-7 text-center shadow-glow animate-scale-in">
            <div
              className="mx-auto flex h-14 w-14 items-center justify-center rounded-full text-2xl"
              style={{ background: 'color-mix(in srgb, var(--dynamic-secondary) 22%, transparent)' }}
            >
              ✅
            </div>
            <h2 className="mt-4 font-display text-xl font-bold">¡Reserva confirmada!</h2>
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
            <p className="mt-2 text-sm text-brand-muted">Elige un horario y reserva. Solo puedes tomar una clase de prueba.</p>

            {error ? (
              <p className="mt-5 rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{error}</p>
            ) : null}

            {loading ? (
              <p className="mt-8 text-sm text-brand-muted">Cargando clases…</p>
            ) : classes.length === 0 ? (
              <div className="mt-8 rounded-2xl border border-brand-line bg-brand-soft/80 p-6 text-center text-sm text-brand-muted">
                Por ahora no hay clases de prueba disponibles. Vuelve más tarde o escríbele al gimnasio.
              </div>
            ) : (
              <ul className="mt-6 space-y-3">
                {classes.map((gymClass) => (
                  <li
                    key={gymClass.id}
                    className="flex items-center justify-between gap-4 rounded-2xl border border-brand-line bg-brand-soft/80 p-4 shadow-soft"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-brand-white">{gymClass.name}</p>
                      <p className="mt-0.5 text-xs capitalize text-brand-muted">{formatWhen(gymClass.start_datetime)}</p>
                      <p className="mt-0.5 text-xs text-brand-dim">
                        {gymClass.branch_name}
                        {gymClass.teacher_name ? ` · ${gymClass.teacher_name}` : ''} · {gymClass.seats_left} cupos
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => book(gymClass)}
                      disabled={bookingId === gymClass.id}
                      className="shrink-0 rounded-xl px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                      style={{ background: 'linear-gradient(to right, var(--dynamic-primary), var(--dynamic-secondary))' }}
                    >
                      {bookingId === gymClass.id ? 'Reservando…' : 'Agendar'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </main>
    </div>
  )
}
