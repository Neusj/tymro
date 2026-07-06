import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { registrationApi, resolveMediaUrl } from '../api/client'

const STATUS = {
  CHECKING: 'checking',
  READY: 'ready',
  INVALID: 'invalid',
  DONE: 'done',
}

function Backdrop() {
  // Atmósfera con los colores del gimnasio (caen a los de marca si no hay).
  return (
    <div
      className="pointer-events-none absolute inset-0"
      style={{
        background:
          'radial-gradient(circle at 12% 18%, color-mix(in srgb, var(--dynamic-primary) 32%, transparent), transparent 30%),' +
          'radial-gradient(circle at 88% 12%, color-mix(in srgb, var(--dynamic-secondary) 28%, transparent), transparent 28%),' +
          'radial-gradient(circle at 50% 110%, color-mix(in srgb, var(--dynamic-primary) 22%, transparent), transparent 34%)',
      }}
    />
  )
}

export default function GymPublicRegisterPage() {
  const [status, setStatus] = useState(STATUS.CHECKING)
  const [org, setOrg] = useState(null)
  const [form, setForm] = useState({ firstName: '', lastName: '', email: '', password: '', phone: '' })
  const [error, setError] = useState('')
  const [existingAccount, setExistingAccount] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let active = true
    const validate = async () => {
      try {
        // La org se resuelve por el subdominio del host (sin slug en el path).
        const data = await registrationApi.validateInvite()
        if (active) {
          setOrg(data)
          setStatus(STATUS.READY)
        }
      } catch {
        if (active) {
          setStatus(STATUS.INVALID)
        }
      }
    }
    validate()
    return () => {
      active = false
    }
  }, [])

  const brandStyle = useMemo(
    () => ({
      '--dynamic-primary': org?.primary_color || '#dc2626',
      '--dynamic-secondary': org?.secondary_color || '#2563eb',
    }),
    [org],
  )

  const update = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }))

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setExistingAccount(false)
    setSubmitting(true)
    try {
      await registrationApi.register({ ...form })
      setStatus(STATUS.DONE)
    } catch (err) {
      const data = err?.response?.data
      const emailError = data?.email?.[0] || ''
      // Si el email ya existe, no es un error muerto: lo guiamos a iniciar sesión.
      if (emailError.toLowerCase().includes('existe')) {
        setExistingAccount(true)
      } else {
        const message =
          data?.detail ||
          emailError ||
          data?.password?.[0] ||
          (typeof data === 'string' ? data : '') ||
          'No se pudo crear la cuenta. Revisa los datos.'
        setError(message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (status === STATUS.CHECKING) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-black text-brand-muted">
        Validando invitación…
      </div>
    )
  }

  if (status === STATUS.INVALID) {
    return (
      <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4 text-center">
        <div className="relative z-10 w-full max-w-md rounded-3xl border border-brand-line bg-brand-soft/95 p-8 shadow-glow">
          <p className="font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
          <h1 className="mt-4 font-display text-2xl font-bold">Link inválido o expirado</h1>
          <p className="mt-3 text-sm text-brand-muted">
            Este enlace de registro no es válido o fue desactivado. Pídele al gimnasio el link actualizado.
          </p>
          <Link
            to="/login"
            className="mt-6 inline-flex min-h-11 items-center rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange"
          >
            Ir a iniciar sesión
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4"
      style={brandStyle}
    >
      <Backdrop />

      <div className="relative z-10 w-full max-w-md">
        {/* Branding del gimnasio: para que la persona sepa que está en el lugar correcto. */}
        <div className="flex flex-col items-center text-center">
          {org?.logo ? (
            <img
              src={resolveMediaUrl(org.logo)}
              alt={org.name}
              className="h-20 w-20 rounded-2xl border border-brand-line object-cover shadow-float"
            />
          ) : (
            <div
              className="flex h-20 w-20 items-center justify-center rounded-2xl border border-brand-line text-2xl font-bold text-brand-white shadow-float"
              style={{ background: 'linear-gradient(135deg, var(--dynamic-primary), var(--dynamic-secondary))' }}
            >
              {(org?.name || '?').slice(0, 2).toUpperCase()}
            </div>
          )}
          <p className="mt-4 font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange">Clase de prueba gratis</p>
          <h1 className="mt-1 font-display text-2xl font-bold text-brand-white sm:text-3xl">{org?.name}</h1>
          <p className="mt-2 text-sm text-brand-muted">Crea tu cuenta y reserva tu primera clase sin costo.</p>
        </div>

        {status === STATUS.DONE ? (
          <div className="mt-7 rounded-3xl border border-brand-line bg-brand-soft/95 p-7 text-center shadow-glow animate-scale-in">
            <div
              className="mx-auto flex h-14 w-14 items-center justify-center rounded-full text-2xl"
              style={{ background: 'color-mix(in srgb, var(--dynamic-secondary) 20%, transparent)' }}
            >
              ✉️
            </div>
            <h2 className="mt-4 font-display text-xl font-bold text-brand-white">Revisa tu email</h2>
            <p className="mt-2 text-sm text-brand-muted">
              Te enviamos un enlace a <span className="font-semibold text-brand-white">{form.email}</span> para
              confirmar tu cuenta. Al confirmarlo podrás agendar tu clase de prueba.
            </p>
          </div>
        ) : (
          <form
            onSubmit={onSubmit}
            className="mt-7 space-y-4 rounded-3xl border border-brand-line bg-brand-soft/95 p-6 shadow-glow sm:p-7"
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block space-y-2">
                <span className="text-sm font-medium text-brand-muted">Nombre</span>
                <input required value={form.firstName} onChange={update('firstName')} className="field min-h-12 px-4" placeholder="Tu nombre" />
              </label>
              <label className="block space-y-2">
                <span className="text-sm font-medium text-brand-muted">Apellido</span>
                <input value={form.lastName} onChange={update('lastName')} className="field min-h-12 px-4" placeholder="Tu apellido" />
              </label>
            </div>

            <label className="block space-y-2">
              <span className="text-sm font-medium text-brand-muted">Email</span>
              <input required type="email" value={form.email} onChange={update('email')} className="field min-h-12 px-4" placeholder="tu@email.com" />
            </label>

            <label className="block space-y-2">
              <span className="text-sm font-medium text-brand-muted">Teléfono <span className="text-brand-dim">(opcional)</span></span>
              <input value={form.phone} onChange={update('phone')} className="field min-h-12 px-4" placeholder="+56 9 ..." />
            </label>

            <label className="block space-y-2">
              <span className="text-sm font-medium text-brand-muted">Contraseña</span>
              <input required type="password" value={form.password} onChange={update('password')} className="field min-h-12 px-4" placeholder="Mínimo 8 caracteres" />
            </label>

            {existingAccount ? (
              <div className="rounded-xl border border-brand-line bg-white/[0.03] p-3 text-sm text-brand-muted">
                Ya tienes una cuenta con ese email.{' '}
                <Link
                  to="/login"
                  state={{ from: { pathname: '/trial' } }}
                  className="font-semibold text-brand-orange underline-offset-4 hover:underline"
                >
                  Inicia sesión para reservar tu clase
                </Link>
                .
              </div>
            ) : null}

            {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{error}</p> : null}

            <button
              type="submit"
              disabled={submitting}
              className="min-h-12 w-full rounded-xl px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
              style={{ background: 'linear-gradient(to right, var(--dynamic-primary), var(--dynamic-secondary))' }}
            >
              {submitting ? 'Creando cuenta…' : 'Crear cuenta y reservar prueba'}
            </button>

            <p className="text-center text-xs text-brand-dim">
              ¿Ya tienes cuenta?{' '}
              <Link to="/login" className="text-brand-muted underline-offset-4 hover:text-brand-orange hover:underline">
                Inicia sesión
              </Link>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
