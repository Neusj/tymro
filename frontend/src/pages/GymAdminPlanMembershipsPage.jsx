import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getPlanById, getPlanMemberships, removePlanMembership } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { getPlanAlertInfo } from '../utils/planAlerts'

function firstApiError(detail, fallback) {
  if (!detail) {
    return fallback
  }
  if (typeof detail === 'string') {
    return detail
  }
  if (detail.detail) {
    return detail.detail
  }
  const firstValue = Object.values(detail)[0]
  if (Array.isArray(firstValue) && firstValue[0]) {
    return firstValue[0]
  }
  return fallback
}

function formatDate(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleDateString()
}

export default function GymAdminPlanMembershipsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [plan, setPlan] = useState(null)
  const [memberships, setMemberships] = useState([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [deleting, setDeleting] = useState(null)

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [planData, membershipsData] = await Promise.all([getPlanById(id), getPlanMemberships(id)])
      setPlan(planData)
      setMemberships(Array.isArray(membershipsData) ? membershipsData : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las membresias del plan.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  const activeCount = useMemo(() => memberships.filter((item) => item.is_active).length, [memberships])

  const removeMembership = async () => {
    if (!deleting) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await removePlanMembership(id, deleting.id)
      setNotice(`Membresia quitada para ${deleting.user_name || deleting.user_email || 'alumno'}.`)
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo quitar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'user_name', label: 'Alumno', render: (row) => row.user_name || `#${row.user}` },
      { key: 'user_email', label: 'Email', render: (row) => row.user_email || '-' },
      { key: 'start_date', label: 'Inicio', render: (row) => formatDate(row.start_date) },
      { key: 'end_date', label: 'Termino', render: (row) => formatDate(row.end_date) },
      { key: 'total_classes', label: 'Clases totales' },
      { key: 'classes_used', label: 'Usadas' },
      { key: 'remaining_classes', label: 'Disponibles' },
      {
        key: 'validity_status',
        label: 'Estado',
        render: (row) => (
          <ValueBadge
            kind="user_status"
            value={
              row.validity_status === 'active'
                ? 'active'
                : row.validity_status === 'expired'
                  ? 'expired'
                  : row.validity_status === 'upcoming'
                    ? 'upcoming'
                    : 'inactive'
            }
          />
        ),
      },
      {
        key: 'alert',
        label: 'Alerta',
        sortable: false,
        render: (row) => {
          const alert = getPlanAlertInfo(row)
          return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${alert.className}`}>{alert.label}</span>
        },
      },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <button
            type="button"
            disabled={working || Number(row.classes_used || 0) > 0}
            onClick={() => setDeleting(row)}
            className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200 disabled:opacity-50"
            title={Number(row.classes_used || 0) > 0 ? 'No se puede quitar si ya utilizo clases.' : ''}
          >
            Quitar plan
          </button>
        ),
      },
    ],
    [working],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={`Membresias · ${plan?.name || 'Plan'}`}
        subtitle="Gestiona alumnos con este plan. Solo puedes quitar membresias sin consumo."
        extra={
          <button type="button" onClick={() => navigate('/gym-admin/plans')} className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white">
            Volver a planes
          </button>
        }
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Total membresias</p>
            <p className="text-xl font-semibold">{memberships.length}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Membresias activas</p>
            <p className="text-xl font-semibold">{activeCount}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Politica actual</p>
            <p className="text-sm font-semibold">Solo sin uso (0 clases)</p>
          </div>
        </div>
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={memberships} loading={loading} />
      </section>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Quitar membresia"
        description={`Se quitara el plan de ${deleting?.user_name || deleting?.user_email || 'este alumno'}. Solo permitido si no ha usado clases.`}
        confirmLabel="Quitar plan"
        loading={working}
        onCancel={() => setDeleting(null)}
        onConfirm={removeMembership}
      />
    </div>
  )
}
