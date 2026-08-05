import { formatDate } from '../utils/format'

// El color por nivel es presentación pura, igual criterio que
// components/ui/PlanAlertBadge.jsx: el backend manda `expiry_alert_level` (severidad)
// y `expiry_alert_message` (texto ya redactado); acá NO se deriva ni traduce nada, solo
// se elige un color. PlanAlertBadge es un pill chico pensado para ir junto a otro dato
// (StudentDashboard); esto es un aviso de ancho completo para la pantalla de
// aterrizaje del alumno, así que es un componente nuevo en vez de reusar el pill.
const LEVEL_STYLES = {
  expired: 'border-brand-red/50 bg-brand-red/10',
  danger: 'border-brand-red/50 bg-brand-red/10',
  warning: 'border-amber-500/50 bg-amber-500/10',
  safe: 'border-emerald-500/50 bg-emerald-500/10',
  neutral: 'border-brand-line bg-black/20',
}

// Banner "tu membresía está por vencer" en /student/classes/available. El backend
// decide CUÁNDO mostrarlo por membresía (`show_expiry_banner`): el front solo filtra
// por ese flag y pinta. Un alumno puede tener 2+ membresías con el flag encendido a la
// vez (planes distintos, cada uno con su propia fecha), así que se listan todas.
export default function MembershipExpiryBanner({ memberships }) {
  const items = (memberships || []).filter((item) => item.show_expiry_banner === true)

  if (items.length === 0) {
    return null
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div
          key={item.id}
          role="alert"
          className={`rounded-xl border px-4 py-3 ${LEVEL_STYLES[item.expiry_alert_level] || LEVEL_STYLES.neutral}`}
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">{item.plan_name || 'Tu plan'}</p>
          <p className="mt-1 text-sm font-medium text-brand-white">{item.expiry_alert_message}</p>
          {item.end_date ? <p className="mt-1 text-xs text-brand-muted">Vence el {formatDate(item.end_date)}</p> : null}
        </div>
      ))}
    </div>
  )
}
