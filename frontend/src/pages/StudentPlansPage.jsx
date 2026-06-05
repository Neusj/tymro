import { useEffect, useMemo, useState } from 'react'
import { getMyMemberships } from '../api/client'
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

export default function StudentPlansPage() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getMyMemberships()
      setPlans(Array.isArray(data) ? data : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus planes vigentes.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const totals = useMemo(
    () => ({
      total: plans.length,
      withBalance: plans.filter((item) => Number(item.remaining_classes || 0) > 0).length,
      withoutBalance: plans.filter((item) => Number(item.remaining_classes || 0) <= 0).length,
    }),
    [plans],
  )

  const columns = useMemo(
    () => [
      { key: 'plan_name', label: 'Plan', render: (row) => row.plan_name || '-' },
      { key: 'start_date', label: 'Inicio', render: (row) => formatDate(row.start_date) },
      { key: 'end_date', label: 'Termino', render: (row) => formatDate(row.end_date) },
      { key: 'classes_used', label: 'Usadas' },
      { key: 'remaining_classes', label: 'Saldo' },
      {
        key: 'validity_status',
        label: 'Estado',
        render: (row) => <ValueBadge kind="user_status" value={row.validity_status === 'active' ? 'active' : 'expired'} />,
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
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Student · Mis planes"
        subtitle="Solo se muestran planes vigentes por fecha. Si vence, desaparece y ya no se puede usar."
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Planes vigentes</p>
            <p className="text-xl font-semibold">{totals.total}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Con saldo</p>
            <p className="text-xl font-semibold">{totals.withBalance}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Sin saldo</p>
            <p className="text-xl font-semibold">{totals.withoutBalance}</p>
          </div>
        </div>
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={plans} loading={loading} />
      </section>
    </div>
  )
}
