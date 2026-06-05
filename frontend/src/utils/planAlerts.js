export function getPlanAlertInfo(plan) {
  const status = String(plan?.validity_status || '').toLowerCase()
  const days = Number.isFinite(Number(plan?.days_to_expiry)) ? Number(plan.days_to_expiry) : null

  if (status === 'expired') {
    return {
      label: 'Vencido',
      level: 'expired',
      className: 'border-brand-red/40 bg-brand-red/10 text-red-200',
    }
  }

  if (status === 'upcoming') {
    return {
      label: 'Por iniciar',
      level: 'safe',
      className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    }
  }

  if (status !== 'active') {
    return {
      label: 'No vigente',
      level: 'neutral',
      className: 'border-brand-line bg-black/20 text-brand-muted',
    }
  }

  if (days !== null && days <= 5) {
    return {
      label: days <= 0 ? 'Vence hoy' : `${days} dias vigentes`,
      level: 'danger',
      className: 'border-brand-red/40 bg-brand-red/10 text-red-200',
    }
  }

  if (days !== null && days <= 12) {
    return {
      label: `${days} dias vigentes`,
      level: 'warning',
      className: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
    }
  }

  if (days !== null) {
    return {
      label: `${days} dias vigentes`,
      level: 'safe',
      className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    }
  }

  return {
    label: 'Vigente',
    level: 'safe',
    className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  }
}
