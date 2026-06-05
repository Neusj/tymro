import { roleLabels } from '../utils/roles'

const roleClasses = {
  superadmin: 'border-brand-blue/40 bg-brand-blue/20 text-brand-white',
  gym_admin: 'border-brand-orange/40 bg-brand-orange/20 text-brand-white',
  teacher: 'border-brand-red/40 bg-brand-red/20 text-brand-white',
  student: 'border-brand-line bg-brand-soft text-brand-white',
}

export default function RoleBadge({ role }) {
  const label = roleLabels[role] || role || 'Sin rol'
  const classes = roleClasses[role] || roleClasses.student

  return <span className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${classes}`}>{label}</span>
}
