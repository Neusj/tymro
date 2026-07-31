// Aviso de vigencia de una membresía. Reemplaza a `utils/planAlerts.js`, que era el QUINTO
// presentador del mismo estado: tenía su propia copia de los umbrales 5/12, su propio
// vocabulario ('No vigente', 'Vigente') y decidía la etiqueta a partir del status.
//
// Acá no se decide nada: el backend manda `*_alert_level` (severidad) y `*_alert_message`
// (texto ya redactado, con los umbrales de `core.services.plans`). Lo único que queda del
// lado del cliente es el color, que es presentación pura.
const LEVEL_CLASSNAMES = {
  expired: 'border-brand-red/40 bg-brand-red/10 text-red-200',
  danger: 'border-brand-red/40 bg-brand-red/10 text-red-200',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  safe: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  neutral: 'border-brand-line bg-black/20 text-brand-muted',
}

export default function PlanAlertBadge({ level, message }) {
  if (!message) {
    return null
  }
  const className = LEVEL_CLASSNAMES[level] || LEVEL_CLASSNAMES.neutral
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      {message}
    </span>
  )
}
