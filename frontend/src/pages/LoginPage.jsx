import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { defaultRouteByRole } from '../utils/roles'
import InstallAppButton from '../components/InstallAppButton'
import {
  buildPublicLandingUrlForWindow,
  buildTenantDisplayHostForWindow,
  buildTenantUrlForWindow,
  resolveHostnameContextForWindow,
} from '../utils/publicLandingHost'

export default function LoginPage() {
  const { login, isAuthenticated, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [accessMode, setAccessMode] = useState('personal')
  const [centerSubdomain, setCenterSubdomain] = useState('')
  const [centerError, setCenterError] = useState('')
  const [loading, setLoading] = useState(false)
  const hostnameContext = resolveHostnameContextForWindow()
  const showAccessSelector = hostnameContext.shouldShowLoginSelector
  const currentAccessMode = showAccessSelector ? accessMode : 'personal'
  const isAdminLogin = hostnameContext.isAdminDomain
  const isTenantLogin = hostnameContext.isTenantDomain

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

  const landingUrl = buildPublicLandingUrlForWindow() || '/'

  const onCenterAccess = (event) => {
    event.preventDefault()
    setCenterError('')

    const tenantUrl = buildTenantUrlForWindow(centerSubdomain)
    if (!tenantUrl) {
      setCenterError('Ingresa el subdominio de tu centro deportivo.')
      return
    }

    window.location.assign(`${tenantUrl}/login`)
  }

  const centerExampleHost = buildTenantDisplayHostForWindow('gladiador')
  const centerDomainSuffix = centerExampleHost ? centerExampleHost.replace(/^gladiador/, '') : ''
  const title = isAdminLogin
    ? 'Acceso administrativo'
    : isTenantLogin
      ? 'Acceso del centro deportivo'
      : 'Inicia sesión'
  const subtitle = showAccessSelector
    ? 'Elige el acceso correcto antes de continuar.'
    : isAdminLogin
      ? 'Ingresa con tus credenciales administrativas.'
      : 'Ingresa con las credenciales de tu centro deportivo.'

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4 lg:p-0">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(220,38,38,0.23),transparent_28%),radial-gradient(circle_at_85%_20%,rgba(37,99,235,0.2),transparent_25%),radial-gradient(circle_at_50%_100%,rgba(249,115,22,0.18),transparent_30%)]" />

      <div className="relative z-10 grid w-full max-w-app overflow-hidden rounded-3xl border border-brand-line bg-brand-soft/95 shadow-glow lg:min-h-[600px] lg:grid-cols-2 lg:rounded-none lg:border-0 lg:bg-transparent lg:shadow-none">
        <a
          href={landingUrl}
          className="absolute left-7 top-7 z-20 inline-flex items-center gap-2 text-sm font-semibold text-brand-muted transition hover:text-brand-orange lg:left-12 lg:top-12"
        >
          <span aria-hidden="true">←</span>
          Volver a TYMRO
        </a>

        {/* Brand panel — desktop only */}
        <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-red/25 via-brand-black to-brand-blue/25 p-12 lg:flex">
          <div className="pointer-events-none absolute -bottom-24 -left-24 h-72 w-72 rounded-full bg-brand-orange/20 blur-3xl" />
          <div aria-hidden="true" className="h-10" />
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
        <div className="flex items-center justify-center p-7 pt-20 sm:p-10 sm:pt-24 lg:bg-brand-soft/95 lg:pt-10">
          <div className="w-full max-w-md">
            <h1 className="font-display text-3xl font-bold">{title}</h1>
            <p className="mt-2 text-sm text-brand-muted">
              {subtitle}
            </p>

            {showAccessSelector ? (
              <div className="login-access-tabs" role="tablist" aria-label="Tipo de acceso">
                <button
                  type="button"
                  role="tab"
                  aria-selected={accessMode === 'personal'}
                  className={accessMode === 'personal' ? 'is-active' : ''}
                  onClick={() => setAccessMode('personal')}
                >
                  Personal
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={accessMode === 'center'}
                  className={accessMode === 'center' ? 'is-active' : ''}
                  onClick={() => setAccessMode('center')}
                >
                  Centro deportivo
                </button>
              </div>
            ) : null}

            {currentAccessMode === 'personal' ? (
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
                  className="login-submit-button"
                >
                  {loading ? 'Ingresando...' : 'Entrar'}
                </button>

                <p className="text-center text-sm">
                  <Link to="/forgot-password" className="text-brand-muted underline-offset-4 hover:text-brand-orange hover:underline">
                    ¿Olvidaste tu contraseña?
                  </Link>
                </p>
              </form>
            ) : (
              <form onSubmit={onCenterAccess} className="mt-7 space-y-4">
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-brand-muted">Subdominio del centro</span>
                  <div className="flex overflow-hidden rounded-xl border border-brand-line bg-black/30 transition focus-within:border-brand-blue">
                    <input
                      required
                      value={centerSubdomain}
                      onChange={(e) => setCenterSubdomain(e.target.value)}
                      className="min-h-12 min-w-0 flex-1 bg-transparent px-4 text-brand-white placeholder:text-brand-dim focus:outline-none"
                      placeholder="gladiador"
                      aria-describedby="center-subdomain-help"
                    />
                    {centerDomainSuffix ? (
                      <span className="hidden items-center border-l border-brand-line px-3 text-sm text-brand-muted sm:flex">
                        {centerDomainSuffix}
                      </span>
                    ) : null}
                  </div>
                  <span id="center-subdomain-help" className="block text-xs text-brand-dim">
                    {centerExampleHost
                      ? `Ejemplo: gladiador te lleva a ${centerExampleHost}`
                      : 'Ejemplo: gladiador te lleva al dominio configurado para esa organización.'}
                  </span>
                </label>

                {centerError ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{centerError}</p> : null}

                <button type="submit" className="login-submit-button">
                  Ir al centro
                </button>
              </form>
            )}

            {/* Instalación PWA: solo aparece si el navegador la ofrece o en iOS; oculto
                si ya corre instalada. No toca la lógica de login. */}
            <InstallAppButton variant="landing" />
          </div>
        </div>
      </div>
    </div>
  )
}
