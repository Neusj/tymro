import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Punto de entrada a la clase de prueba gratis DESDE la app (no solo por el redirect
// post-verificación): un alumno logueado o importado no tenía cómo llegar a /trial.
// Persistente y con el mismo estilo que RutReminderBanner. Solo para alumnos que aún
// no usaron su prueba; desaparece en cuanto has_used_trial pasa a true.
export default function TrialClassBanner() {
  const { user } = useAuth()

  // Los flags viajan en /me (CustomUserSerializer, solo lectura). Sin usuario, si no
  // es alumno, o si ya usó la prueba, no hay banner.
  if (!user || user.role !== 'student' || user.has_used_trial) {
    return null
  }

  // Sin email verificado el backend no deja agendar: en vez del CTA se invita a
  // confirmar el correo, reusando el mensaje del registro público. No hay endpoint
  // de reenvío de verificación, así que esta variante es informativa.
  if (!user.email_verified) {
    return (
      <div className="mb-5 rounded-xl border border-brand-orange/50 bg-brand-orange/10 px-4 py-3">
        <p className="text-sm font-semibold text-brand-white">✉️ Confirma tu correo para agendar tu clase de prueba</p>
        <p className="mt-1 text-xs text-brand-muted">
          Te enviamos un enlace para confirmar tu cuenta. Revisa tu bandeja de entrada (y spam);
          al confirmarlo podrás agendar tu clase de prueba gratis.
        </p>
      </div>
    )
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
