import { useEffect, useMemo, useState } from 'react'
import { getMyMemberships, paymentsApi } from '../api/client'
import useRefetchOnForeground from '../hooks/useRefetchOnForeground'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import { clp, formatDate } from '../utils/format'

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

export default function StudentPlansPage() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [payingId, setPayingId] = useState(null)

  const handlePayEnrollment = async (row) => {
    setPayingId(row.id)
    setError('')
    try {
      const { redirect_url: url } = await paymentsApi.checkout({ targetStudentPlanId: row.id })
      if (!url) throw new Error('sin url')
      window.location.assign(url)
    } catch (apiError) {
      setPayingId(null)
      const statusCode = apiError?.response?.status
      if (statusCode === 409) {
        setError('El gimnasio aún no habilitó pagos en línea. Escríbeles para activarlo.')
      } else {
        setError(firstApiError(apiError?.response?.data, 'No se pudo iniciar el pago de la matrícula.'))
      }
    }
  }

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

  // PWA: al volver del foco (p. ej. tras pagar en Checkout Pro) recarga los planes.
  useRefetchOnForeground(loadData)

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
        // La etiqueta la manda el backend (`_LABELS`). El ternario que había acá colapsaba
        // los siete estados a "Activa"/"Vencido", así que un plan sin saldo —vigente por
        // fecha— se mostraba como vencido justo al lado del botón de pago.
        //
        // Sigue siendo un chip y no texto pelado: en móvil DataTable manda esta celda a la
        // zona `meta`, que NO aporta estilo propio, así que el color tiene que venir del
        // contenido. La severidad la decide el backend; acá no se deriva nada.
        render: (row) => <PlanAlertBadge level={row.expiry_alert_level} message={row.validity_status_label} />,
      },
      {
        key: 'alert',
        label: 'Alerta',
        sortable: false,
        render: (row) => <PlanAlertBadge level={row.expiry_alert_level} message={row.expiry_alert_message} />,
      },
      {
        key: 'matricula',
        label: 'Matrícula',
        sortable: false,
        render: (row) => {
          const status = row.enrollment_fee_status?.status
          const fee = Number(row.enrollment_fee || 0)
          if (status === 'paid') {
            return (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-200">
                Pagada
              </span>
            )
          }
          if ((status === 'pending' || status === 'overdue') && fee > 0) {
            return (
              <button
                type="button"
                onClick={() => handlePayEnrollment(row)}
                disabled={payingId === row.id}
                className="inline-flex items-center gap-1.5 rounded-lg border border-brand-orange/50 px-2.5 py-1 text-xs font-semibold text-brand-orange transition hover:bg-brand-orange/10 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {payingId === row.id ? 'Redirigiendo…' : `Pagar matrícula · ${clp(fee)}`}
              </button>
            )
          }
          return <span className="text-xs text-brand-dim">—</span>
        },
      },
    ],
    [payingId],
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
