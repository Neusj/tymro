import { useEffect, useMemo, useState } from 'react'
import { teacherPaymentsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('es-CL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

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

export default function TeacherPaymentsPage() {
  const [payments, setPayments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadPayments = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await teacherPaymentsApi.my()
      setPayments(Array.isArray(data) ? data : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus pagos.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPayments()
  }, [])

  const totalAmount = useMemo(
    () => payments.reduce((sum, item) => sum + (Number(item.total_amount) || 0), 0),
    [payments],
  )

  const columns = useMemo(
    () => [
      { key: 'calculated_at', label: 'Fecha', mobile: 'secondary', mobilePriority: 2, render: (row) => formatDateTime(row.calculated_at) },
      { key: 'class_name', label: 'Clase', mobile: 'title', render: (row) => row.class_name || `Clase #${row.class_instance}` },
      { key: 'total_students', label: 'Alumnos considerados', mobile: 'secondary', mobilePriority: 3, mobileLabel: 'Alumnos' },
      { key: 'payment_type', label: 'Tipo', mobile: 'meta', render: (row) => <ValueBadge kind="payment_type" value={row.payment_type} /> },
      {
        key: 'total_amount',
        label: 'Monto ganado',
        mobile: 'secondary',
        mobilePriority: 1,
        mobileLabel: 'Monto',
        render: (row) => `$${Number(row.total_amount || 0).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader title="Teacher · Mis pagos" subtitle="Pagos calculados por clases cerradas." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="rounded-xl border border-brand-line bg-black/20 p-3">
          <p className="text-xs text-brand-muted">Total acumulado</p>
          <p className="text-2xl font-semibold">${totalAmount.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
        </div>
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={payments} loading={loading} defaultSort={{ key: 'calculated_at', direction: 'desc' }} />
      </section>
    </div>
  )
}
