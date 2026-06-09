import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../api/client'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const uid = searchParams.get('uid') || ''
  const token = searchParams.get('token') || ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  const missingParams = !uid || !token

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')

    if (password !== confirm) {
      setError('Las contraseñas no coinciden.')
      return
    }

    setLoading(true)
    try {
      await authApi.confirmPasswordReset({ uid, token, newPassword: password })
      setDone(true)
      setTimeout(() => navigate('/login', { replace: true }), 2500)
    } catch (err) {
      const data = err?.response?.data
      const message =
        data?.detail ||
        (Array.isArray(data?.new_password) ? data.new_password.join(' ') : null) ||
        'No se pudo restablecer la contraseña. Pide un nuevo enlace.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(220,38,38,0.23),transparent_28%),radial-gradient(circle_at_85%_20%,rgba(37,99,235,0.2),transparent_25%),radial-gradient(circle_at_50%_100%,rgba(249,115,22,0.18),transparent_30%)]" />

      <div className="relative z-10 w-full max-w-md rounded-3xl border border-brand-line bg-brand-soft/95 p-7 shadow-glow sm:p-10">
        <p className="font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
        <h1 className="mt-3 font-display text-3xl font-bold">Nueva contraseña</h1>

        {done ? (
          <div className="mt-6 space-y-5">
            <p className="rounded-xl border border-green-500/40 bg-green-500/10 p-4 text-sm text-green-100">
              Contraseña actualizada. Te llevamos al inicio de sesión...
            </p>
            <Link to="/login" className="block text-center text-sm text-brand-orange underline-offset-4 hover:underline">
              Ir a iniciar sesión
            </Link>
          </div>
        ) : missingParams ? (
          <div className="mt-6 space-y-5">
            <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-4 text-sm text-red-100">
              El enlace no es válido o está incompleto. Pide uno nuevo desde "¿Olvidaste tu contraseña?".
            </p>
            <Link to="/forgot-password" className="block text-center text-sm text-brand-orange underline-offset-4 hover:underline">
              Pedir nuevo enlace
            </Link>
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm text-brand-muted">Elige una contraseña nueva y segura.</p>

            <form onSubmit={onSubmit} className="mt-7 space-y-4">
              <label className="block space-y-2">
                <span className="text-sm font-medium text-brand-muted">Nueva contraseña</span>
                <input
                  required
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="field min-h-12 px-4"
                  placeholder="••••••••"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-sm font-medium text-brand-muted">Repetir contraseña</span>
                <input
                  required
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="field min-h-12 px-4"
                  placeholder="••••••••"
                />
              </label>

              {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{error}</p> : null}

              <button
                type="submit"
                disabled={loading}
                className="min-h-12 w-full rounded-xl bg-gradient-to-r from-brand-red via-brand-orange to-brand-blue px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Guardando...' : 'Restablecer contraseña'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
