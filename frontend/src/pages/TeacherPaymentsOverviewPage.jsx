import { useEffect, useMemo, useState } from 'react'
import { teacherPaymentsApi, usersApi } from '../api/client'
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

export default function TeacherPaymentsOverviewPage() {
  const [payments, setPayments] = useState([])
  const [teachers, setTeachers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({
    teacher_id: '',
    date_from: '',
    date_to: '',
  })

  const loadTeachers = async () => {
    try {
      const data = await usersApi.list({ role: 'teacher' })
      setTeachers(Array.isArray(data) ? data : [])
    } catch {
      setTeachers([])
    }
  }

  const loadPayments = async (currentFilters = filters) => {
    setLoading(true)
    setError('')
    try {
      const params = {}
      if (currentFilters.teacher_id) {
        params.teacher_id = currentFilters.teacher_id
      }
      if (currentFilters.date_from) {
        params.date_from = currentFilters.date_from
      }
      if (currentFilters.date_to) {
        params.date_to = currentFilters.date_to
      }
      const data = await teacherPaymentsApi.list(params)
      setPayments(Array.isArray(data) ? data : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar pagos de profesores.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTeachers()
    loadPayments()
  }, [])

  const totalAmount = useMemo(
    () => payments.reduce((sum, item) => sum + (Number(item.total_amount) || 0), 0),
    [payments],
  )

  const columns = useMemo(
    () => [
      { key: 'teacher_name', label: 'Profesor' },
      { key: 'class_name', label: 'Clase', render: (row) => row.class_name || `Clase #${row.class_instance}` },
      { key: 'payment_type', label: 'Tipo', render: (row) => <ValueBadge kind="payment_type" value={row.payment_type} /> },
      { key: 'total_students', label: 'Alumnos' },
      { key: 'total_amount', label: 'Monto', render: (row) => `$${Number(row.total_amount || 0).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` },
      { key: 'calculated_at', label: 'Fecha', render: (row) => formatDateTime(row.calculated_at) },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader title="Pagos Profesores · Resumen" subtitle="Pagos generados automaticamente al cerrar clases." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="space-y-1 text-sm">
            <span className="text-brand-muted">Profesor</span>
            <select
              value={filters.teacher_id}
              onChange={(event) => setFilters((prev) => ({ ...prev, teacher_id: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Todos</option>
              {teachers.map((teacher) => (
                <option key={teacher.id} value={teacher.id}>
                  {`${teacher.first_name || ''} ${teacher.last_name || ''}`.trim() || teacher.username}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-brand-muted">Desde</span>
            <input
              type="date"
              value={filters.date_from}
              onChange={(event) => setFilters((prev) => ({ ...prev, date_from: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-brand-muted">Hasta</span>
            <input
              type="date"
              value={filters.date_to}
              onChange={(event) => setFilters((prev) => ({ ...prev, date_to: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={() => loadPayments(filters)}
              className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-black transition hover:brightness-110"
            >
              Filtrar
            </button>
            <button
              type="button"
              onClick={() => {
                const reset = { teacher_id: '', date_from: '', date_to: '' }
                setFilters(reset)
                loadPayments(reset)
              }}
              className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white"
            >
              Limpiar
            </button>
          </div>
        </div>
      </section>

      <section className="card-surface space-y-4 p-5">
        <div className="rounded-xl border border-brand-line bg-black/20 p-3">
          <p className="text-xs text-brand-muted">Total acumulado filtrado</p>
          <p className="text-2xl font-semibold">${totalAmount.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
        </div>
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={payments} loading={loading} defaultSort={{ key: 'calculated_at', direction: 'desc' }} />
      </section>
    </div>
  )
}
