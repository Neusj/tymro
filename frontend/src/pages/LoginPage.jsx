import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { defaultRouteByRole } from '../utils/roles'

export default function LoginPage() {
  const { login, isAuthenticated, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (isAuthenticated && user) {
    return <Navigate to={defaultRouteByRole(user.role)} replace />
  }

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      const currentUser = await login(email, password)
      const fromLocation = location.state?.from
      const from = fromLocation ? `${fromLocation.pathname || ''}${fromLocation.search || ''}` : ''
      navigate(from && from !== '/login' ? from : defaultRouteByRole(currentUser.role), { replace: true })
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo iniciar sesión.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4 lg:p-0">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(220,38,38,0.23),transparent_28%),radial-gradient(circle_at_85%_20%,rgba(37,99,235,0.2),transparent_25%),radial-gradient(circle_at_50%_100%,rgba(249,115,22,0.18),transparent_30%)]" />

      <div className="relative z-10 grid w-full max-w-app overflow-hidden rounded-3xl border border-brand-line bg-brand-soft/95 shadow-glow lg:min-h-[600px] lg:grid-cols-2 lg:rounded-none lg:border-0 lg:bg-transparent lg:shadow-none">
        {/* Brand panel — desktop only */}
        <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-red/25 via-brand-black to-brand-blue/25 p-12 lg:flex">
          <div className="pointer-events-none absolute -bottom-24 -left-24 h-72 w-72 rounded-full bg-brand-orange/20 blur-3xl" />
          <p className="font-display text-sm font-bold uppercase tracking-[0.4em] text-brand-orange">TYMRO</p>
          <div className="relative">
            <h2 className="font-display text-4xl font-bold leading-tight text-brand-white xl:text-5xl">
              Gestiona tu gimnasio<br />sin fricción.
            </h2>
            <p className="mt-4 max-w-sm text-sm text-brand-muted">
              Clases, reservas, planes y pagos a profesores en una sola plataforma multi-organización.
            </p>
            <div className="mt-8 flex flex-wrap gap-2">
              {['Multi-sucursal', 'Reservas y recurrencias', 'Pagos a profesores'].map((tag) => (
                <span key={tag} className="badge-accent border-brand-hairline bg-white/[0.03]">{tag}</span>
              ))}
            </div>
          </div>
          <p className="relative text-xs text-brand-dim">Acceso por rol · Superadmin · Admin · Profesor · Alumno</p>
        </div>

        {/* Form panel */}
        <div className="flex items-center justify-center p-7 sm:p-10 lg:bg-brand-soft/95">
          <div className="w-full max-w-md">
            <p className="font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange lg:hidden">TYMRO</p>
            <h1 className="mt-3 font-display text-3xl font-bold lg:mt-0">Inicia sesión</h1>
            <p className="mt-2 text-sm text-brand-muted">Ingresa con tu email y contraseña.</p>

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

              <label className="block space-y-2">
                <span className="text-sm font-medium text-brand-muted">Contraseña</span>
                <input
                  required
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
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
                {loading ? 'Ingresando...' : 'Entrar'}
              </button>

              <p className="text-center text-sm">
                <Link to="/forgot-password" className="text-brand-muted underline-offset-4 hover:text-brand-orange hover:underline">
                  ¿Olvidaste tu contraseña?
                </Link>
              </p>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}
