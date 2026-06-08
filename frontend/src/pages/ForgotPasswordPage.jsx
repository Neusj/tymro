import { useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../api/client'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      await authApi.requestPasswordReset(email)
      setDone(true)
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo procesar la solicitud. Intentá de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(220,38,38,0.23),transparent_28%),radial-gradient(circle_at_85%_20%,rgba(37,99,235,0.2),transparent_25%),radial-gradient(circle_at_50%_100%,rgba(249,115,22,0.18),transparent_30%)]" />

      <div className="relative z-10 w-full max-w-md rounded-3xl border border-brand-line bg-brand-soft/95 p-7 shadow-glow sm:p-10">
        <p className="font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
        <h1 className="mt-3 font-display text-3xl font-bold">Recuperar contraseña</h1>

        {done ? (
          <div className="mt-6 space-y-5">
            <p className="rounded-xl border border-brand-line bg-white/[0.03] p-4 text-sm text-brand-muted">
              Si el email existe en el sistema, te enviamos un enlace para restablecer tu contraseña.
              Revisá tu bandeja de entrada (y spam).
            </p>
            <Link to="/login" className="block text-center text-sm text-brand-orange underline-offset-4 hover:underline">
              Volver a iniciar sesión
            </Link>
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm text-brand-muted">
              Ingresá tu email y te enviaremos instrucciones para crear una nueva contraseña.
            </p>

            <form onSubmit={onSubmit} className="mt-7 space-y-4">
              <label className="block space-y-2">
                <span className="text-sm font-medium text-brand-muted">Email</span>
                <input
                  required
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="field min-h-12 px-4"
                  placeholder="tu@email.com"
                />
              </label>

              {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{error}</p> : null}

              <button
                type="submit"
                disabled={loading}
                className="min-h-12 w-full rounded-xl bg-gradient-to-r from-brand-red via-brand-orange to-brand-blue px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Enviando...' : 'Enviar instrucciones'}
              </button>

              <p className="text-center text-sm">
                <Link to="/login" className="text-brand-muted underline-offset-4 hover:text-brand-orange hover:underline">
                  Volver a iniciar sesión
                </Link>
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
