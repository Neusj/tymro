import { useCallback, useEffect, useMemo, useState } from 'react'
import { getMyPlan } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import useRefetchOnForeground from '../hooks/useRefetchOnForeground'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import SectionCard from '../components/SectionCard'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import { formatDate } from '../utils/format'

function ProfileImage({ user }) {
  if (user?.profile_image) {
    return <img src={user.profile_image} alt={user.username} className="h-16 w-16 rounded-2xl border border-brand-line object-cover" />
  }

  const initials = `${user?.first_name?.[0] || ''}${user?.last_name?.[0] || ''}`.trim() || 'S'
  return (
    <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-brand-line bg-brand-orange/20 text-xl font-bold">
      {initials.toUpperCase()}
    </div>
  )
}

export default function StudentDashboard() {
  const { user } = useAuth()
  const [myPlan, setMyPlan] = useState(null)

  const loadPlan = useCallback(async () => {
    try {
      const data = await getMyPlan()
      setMyPlan(data || null)
    } catch {
      setMyPlan(null)
    }
  }, [])

  useEffect(() => {
    loadPlan()
  }, [loadPlan])

  // PWA: al volver del foco (p. ej. tras pagar en Checkout Pro) re-pide el plan.
  useRefetchOnForeground(loadPlan)

  // La vigencia NO se recalcula acá. Antes era `is_active && end_date >= today` con un
  // `today` sacado de `toISOString()` (UTC), así que a partir de las 20:00 de Chile el
  // último día del plan la tarjeta decía "Vencido" mientras el backend —y la reserva— lo
  // seguían aceptando. El estado lo resuelve `describe_student_plan` y viaja ya etiquetado.
  const remaining = Math.max((myPlan?.total_classes || 0) - (myPlan?.classes_used || 0), 0)
  const statusLabel = myPlan?.active_freeze ? 'Congelada' : myPlan?.validity_status_label
  const statusLevel = myPlan?.active_freeze ? 'warning' : myPlan?.expiry_alert_level
  const statusMessage = myPlan?.active_freeze ? 'Membresia congelada' : myPlan?.expiry_alert_message
  const usagePercent = myPlan?.total_classes ? Math.round(((myPlan?.classes_used || 0) / myPlan.total_classes) * 100) : 0

  const progressClass = useMemo(() => {
    if (remaining <= 0) {
      return 'bg-brand-red'
    }
    const remainingRatio = myPlan?.total_classes ? remaining / myPlan.total_classes : 0
    if (remainingRatio > 0.5) {
      return 'bg-emerald-500'
    }
    return 'bg-amber-500'
  }, [myPlan?.total_classes, remaining])

  return (
    <div className="space-y-6">
      <DashboardHeader title="Dashboard Student" subtitle="Tu perfil y próximos módulos del producto" />

      <section className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Perfil" subtitle="Información de tu cuenta">
          <div className="flex items-center gap-4 rounded-xl border border-brand-line bg-black/20 p-4">
            <ProfileImage user={user} />
            <div>
              <p className="text-lg font-semibold">{`${user?.first_name || ''} ${user?.last_name || ''}`.trim() || user?.username}</p>
              <p className="text-sm text-brand-muted">{user?.email || 'Sin email'}</p>
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-brand-line p-3">
              <p className="text-xs uppercase tracking-wide text-brand-muted">Organización</p>
              <p className="mt-1 text-sm font-semibold">{user?.organization_detail?.name || 'Sin organización'}</p>
            </div>
            <div className="rounded-xl border border-brand-line p-3">
              <p className="text-xs uppercase tracking-wide text-brand-muted">Sucursal</p>
              <p className="mt-1 text-sm font-semibold">{user?.branch_detail?.name || 'Sin sucursal'}</p>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Mi Plan" subtitle="Consumo y estado actual de tu plan">
          {myPlan ? (
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-brand-line p-3">
                  <p className="text-xs uppercase tracking-wide text-brand-muted">Nombre</p>
                  <p className="mt-1 text-sm font-semibold">{myPlan.plan_name || '-'}</p>
                </div>
                <div className="rounded-xl border border-brand-line p-3">
                  <p className="text-xs uppercase tracking-wide text-brand-muted">Estado</p>
                  <p className="mt-1 text-sm font-semibold">{statusLabel || '-'}</p>
                  <span className="mt-2 block">
                    <PlanAlertBadge level={statusLevel} message={statusMessage} />
                  </span>
                </div>
                <div className="rounded-xl border border-brand-line p-3">
                  <p className="text-xs uppercase tracking-wide text-brand-muted">Inicio / Fin</p>
                  <p className="mt-1 text-sm font-semibold">{formatDate(myPlan.start_date)} / {formatDate(myPlan.end_date)}</p>
                </div>
                <div className="rounded-xl border border-brand-line p-3">
                  <p className="text-xs uppercase tracking-wide text-brand-muted">Clases disponibles</p>
                  <p className="mt-1 text-sm font-semibold">{remaining}</p>
                </div>
                <div className="rounded-xl border border-brand-line p-3 sm:col-span-2">
                  <p className="text-xs uppercase tracking-wide text-brand-muted">Clases usadas</p>
                  <p className="mt-1 text-sm font-semibold">{myPlan.classes_used} / {myPlan.total_classes}</p>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-brand-line">
                    <div className={`h-2 ${progressClass}`} style={{ width: `${Math.min(usagePercent, 100)}%` }} />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <EmptyState title="Sin plan activo" description="Aquí verás nombre, fechas y consumo de tu plan cuando esté asignado." />
          )}
        </SectionCard>
      </section>
    </div>
  )
}
