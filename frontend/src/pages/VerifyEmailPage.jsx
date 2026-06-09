import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { registrationApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const STATUS = {
  VERIFYING: 'verifying',
  OK: 'ok',
  ERROR: 'error',
}

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { loginWithToken } = useAuth()
  const uid = searchParams.get('uid') || ''
  const token = searchParams.get('token') || ''
  const [status, setStatus] = useState(STATUS.VERIFYING)
  const ranRef = useRef(false)

  useEffect(() => {
    // Evita doble ejecución en StrictMode (el token de verificación es de un solo uso).
    if (ranRef.current) {
      return
    }
    ranRef.current = true

    const verify = async () => {
      if (!uid || !token) {
        setStatus(STATUS.ERROR)
        return
      }
      try {
        const data = await registrationApi.verifyEmail({ uid, token })
        loginWithToken(data.token, data.user)
        setStatus(STATUS.OK)
        navigate('/trial', { replace: true })
      } catch {
        setStatus(STATUS.ERROR)
      }
    }
    verify()
  }, [uid, token, loginWithToken, navigate])

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-black p-4 text-center">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(37,99,235,0.18),transparent_35%)]" />
      <div className="relative z-10 w-full max-w-md rounded-3xl border border-brand-line bg-brand-soft/95 p-8 shadow-glow">
        <p className="font-display text-xs font-bold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>

        {status === STATUS.VERIFYING ? (
          <>
            <h1 className="mt-4 font-display text-2xl font-bold">Confirmando tu email…</h1>
            <p className="mt-3 text-sm text-brand-muted">Un segundo, estamos activando tu cuenta.</p>
          </>
        ) : null}

        {status === STATUS.ERROR ? (
          <>
            <h1 className="mt-4 font-display text-2xl font-bold">El enlace no es válido</h1>
            <p className="mt-3 text-sm text-brand-muted">
              El enlace de confirmación no es válido o ya expiró. Vuelve a registrarte o pide uno nuevo.
            </p>
            <Link
              to="/login"
              className="mt-6 inline-flex min-h-11 items-center rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange"
            >
              Ir a iniciar sesión
            </Link>
          </>
        ) : null}
      </div>
    </div>
  )
}
