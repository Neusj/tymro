function resolveConfig(kind, value) {
  const normalized = String(value ?? '').trim().toLowerCase()

  const common = {
    base: 'inline-flex items-center gap-1 rounded-full border bg-white/[0.04] px-2.5 py-0.5 text-[11px] font-semibold',
    neutral: 'border-brand-line text-brand-white',
  }

  const statusMap = {
    scheduled: { label: 'Reservada', cls: 'border-brand-blue/40 text-blue-200' },
    in_progress: { label: 'En curso', cls: 'border-brand-orange/40 text-amber-200' },
    completed: { label: 'Finalizada', cls: 'border-emerald-500/40 text-emerald-200' },
    completed_early: { label: 'Finalizada anticipadamente', cls: 'border-amber-500/40 text-amber-200' },
    cancelled: { label: 'Cancelada', cls: 'border-brand-red/40 text-red-200' },
    active: { label: 'Activa', cls: 'border-emerald-500/40 text-emerald-200' },
    inactive: { label: 'Inactiva', cls: 'border-brand-line text-brand-muted' },
    paused: { label: 'Pausada', cls: 'border-amber-500/40 text-amber-200' },
    expired: { label: 'Vencido', cls: 'border-brand-red/40 text-red-200' },
    upcoming: { label: 'Por iniciar', cls: 'border-emerald-500/40 text-emerald-200' },
    no_plan: { label: 'Sin plan', cls: 'border-brand-line text-brand-muted' },
  }

  if (kind === 'class_status' || kind === 'template_status' || kind === 'enrollment_status' || kind === 'user_status') {
    const config = statusMap[normalized]
    if (config) {
      return { label: config.label, className: `${common.base} ${config.cls}` }
    }
    return { label: value || '-', className: `${common.base} ${common.neutral}` }
  }

  if (kind === 'reservation_kind') {
    if (normalized === 'recurring') {
      return { label: 'Recurrente', className: `${common.base} border-brand-orange/40 text-amber-200` }
    }
    return { label: 'Individual', className: `${common.base} border-brand-blue/40 text-blue-200` }
  }

  if (kind === 'attendance_status') {
    const attendanceMap = {
      present: { label: 'Presente', cls: 'border-emerald-500/40 text-emerald-200' },
      absent: { label: 'Ausente', cls: 'border-brand-red/40 text-red-200' },
      late: { label: 'Tarde', cls: 'border-amber-500/40 text-amber-200' },
      excused: { label: 'Justificado', cls: 'border-cyan-500/40 text-cyan-200' },
      no_show: { label: 'No asistió', cls: 'border-brand-line text-brand-muted' },
    }
    const config = attendanceMap[normalized]
    if (config) {
      return { label: config.label, className: `${common.base} ${config.cls}` }
    }
    return { label: 'Sin marcar', className: `${common.base} ${common.neutral}` }
  }

  if (kind === 'class_type') {
    return { label: value || '-', className: `${common.base} border-cyan-500/40 text-cyan-200` }
  }

  if (kind === 'payment_type') {
    if (normalized === 'fixed_per_class') {
      return { label: 'Fijo por clase', className: `${common.base} border-cyan-500/40 text-cyan-200` }
    }
    if (normalized === 'per_student') {
      return { label: 'Por alumno', className: `${common.base} border-emerald-500/40 text-emerald-200` }
    }
    if (normalized === 'revenue_share') {
      return { label: '% ingreso', className: `${common.base} border-amber-500/40 text-amber-200` }
    }
    return { label: value || '-', className: `${common.base} ${common.neutral}` }
  }

  if (kind === 'discipline') {
    return { label: value || '-', className: `${common.base} border-orange-500/40 text-orange-200` }
  }

  return { label: value || '-', className: `${common.base} ${common.neutral}` }
}

export default function ValueBadge({ kind = 'generic', value }) {
  const { label, className } = resolveConfig(kind, value)
  return <span className={className}>{label}</span>
}
