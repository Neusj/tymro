import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { BRAND_ICON } from '../config/publicLanding'
import { defaultRouteByRole } from '../utils/roles'

function SessionLoadingMark() {
  return (
    <span className="login-loading-mark login-loading-mark-lg" aria-hidden="true">
      <img src={BRAND_ICON} alt="" width="28" height="28" />
    </span>
  )
}

export default function ProtectedRoute({ allowedRoles, children }) {
  const { user, loading, isAuthenticated, bootstrapError, verifying, retryBootstrap } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-brand-muted">
        <SessionLoadingMark />
        <span>Cargando sesión...</span>
      </div>
    )
  }

  // No se pudo verificar la sesión por un fallo transitorio (timeout/red). No se
  // expulsa al login —el token puede seguir siendo válido— pero tampoco se
  // renderiza la app con el usuario cacheado: se ofrece reintentar.
  if (bootstrapError) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <section className="card-surface w-full max-w-sm p-6 text-center">
          <p className="font-display text-lg font-semibold text-brand-white">No pudimos verificar tu sesión</p>
          <p className="mt-2 text-sm text-brand-muted">{bootstrapError}</p>
          <button
            type="button"
            onClick={retryBootstrap}
            disabled={verifying}
            className="mt-5 rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {verifying ? 'Verificando…' : 'Reintentar'}
          </button>
        </section>
      </div>
    )
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={defaultRouteByRole(user.role)} replace />
  }

  return children
}
