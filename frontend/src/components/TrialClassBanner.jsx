import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { authApi } from '../api/client'

// Botón de reenvío del correo de confirmación (#26). POSTea a /resend-verification/
// por la instancia axios AUTENTICADA (authApi). Máquina de estados sencilla:
// idle → enviando → enviado; un 429 (throttle) muestra "ya enviamos uno recién".
function ResendVerificationButton() {
  const [status, setStatus] = useState('idle') // idle | sending | sent | rate_limited | error

  const handleResend = async () => {
    if (status === 'sending') {
      return
    }
    setStatus('sending')
    try {
      await authApi.resendVerification()
      setStatus('sent')
    } catch (err) {
      setStatus(err?.response?.status === 429 ? 'rate_limited' : 'error')
    }
  }

  if (status === 'sent') {
    return (
      <p className="mt-3 text-xs font-semibold text-brand-white">
        ✅ Te reenviamos el correo. Revisa tu bandeja de entrada (y spam).
      </p>
    )
  }

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={handleResend}
        disabled={status === 'sending'}
        className="inline-flex rounded-lg border border-brand-orange px-3 py-1.5 text-xs font-semibold text-brand-white disabled:opacity-60"
      >
        {status === 'sending' ? 'Enviando…' : 'Reenviar correo de confirmación'}
      </button>
      {status === 'rate_limited' && (
        <p className="mt-2 text-xs text-brand-muted">
          Ya enviamos uno recién. Revisa tu bandeja de entrada (y spam).
        </p>
      )}
      {status === 'error' && (
        <p className="mt-2 text-xs text-brand-muted">
          No pudimos reenviarlo. Inténtalo de nuevo en un momento.
        </p>
      )}
    </div>
  )
}

// Punto de entrada a la clase de prueba gratis DESDE la app (no solo por el redirect
// post-verificación). Solo para alumnos que vienen del registro público y aún no
// usaron su prueba; para los demás conserva solo el aviso de confirmar correo.
export default function TrialClassBanner() {
  const { user } = useAuth()

  // Los flags viajan en /me (CustomUserSerializer, solo lectura). Sin usuario o si
  // no es alumno no hay aviso desde este componente.
  if (!user || user.role !== 'student') {
    return null
  }

  const canUseTrial = user.trial_eligible && !user.has_used_trial

  // Sin email verificado se mantiene el aviso de confirmación para todos los
  // alumnos. Si no tiene prueba gratis disponible, el texto no promete agendarla.
  if (!user.email_verified) {
    return (
      <div className="mb-5 rounded-xl border border-brand-orange/50 bg-brand-orange/10 px-4 py-3">
        <p className="text-sm font-semibold text-brand-white">
          {canUseTrial ? '✉️ Confirma tu correo para agendar tu clase de prueba' : '✉️ Confirma tu correo'}
        </p>
        <p className="mt-1 text-xs text-brand-muted">
          {canUseTrial
            ? 'Te enviamos un enlace para confirmar tu cuenta. Revisa tu bandeja de entrada (y spam); al confirmarlo podrás agendar tu clase de prueba gratis.'
            : 'Te enviamos un enlace para confirmar tu cuenta. Revisa tu bandeja de entrada (y spam); al confirmarlo tu cuenta quedará activa.'}
        </p>
        <ResendVerificationButton />
      </div>
    )
  }

  if (!canUseTrial) {
    return null
  }

  return (
    <div className="mb-5 rounded-xl border border-brand-orange/50 bg-brand-orange/10 px-4 py-3">
      <p className="text-sm font-semibold text-brand-white">🎁 Tienes una clase de prueba gratis</p>
      <p className="mt-1 text-xs text-brand-muted">
        Agéndala cuando quieras: elige el día y la hora que más te acomoden.
      </p>
      <div className="mt-3">
        <Link
          to="/trial"
          className="inline-flex rounded-lg bg-brand-orange px-4 py-2 text-sm font-semibold text-white"
        >
          Agéndala aquí
        </Link>
      </div>
    </div>
  )
}
