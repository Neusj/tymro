import { useEffect, useMemo, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import FilterDropdown from '../components/FilterDropdown'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { enrollmentsApi, recurringEnrollmentsApi } from '../api/client'
import {
  applyStudentRecurringFilters,
  calculateRecurringKpis,
  extractStudentRecurringOptions,
  formatDateTime,
} from './studentClasses.helpers'

const initialFilters = {
  teacher: '',
  discipline: '',
  status: '',
}

const statusOptions = [
  { value: '', label: 'Todas' },
  { value: 'active', label: 'Activas' },
  { value: 'paused', label: 'Pausadas' },
]

const weekdayLabels = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

function formatDate(value) {
  if (!value) {
    return '-'
  }
  return new Date(`${value}T00:00:00`).toLocaleDateString('es-CL', { dateStyle: 'medium' })
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

export default function StudentRecurringEnrollmentsPage() {
  const [items, setItems] = useState([])
  const [futureByRecurring, setFutureByRecurring] = useState({})
  const [filters, setFilters] = useState(initialFilters)
  const [loading, setLoading] = useState(true)
  const [workingId, setWorkingId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const loadData = async () => {
    setLoading(true)
    try {
      const [data, enrollments] = await Promise.all([recurringEnrollmentsApi.my(), enrollmentsApi.my()])
      const now = Date.now()
      const futureMap = {}
      enrollments.forEach((item) => {
        if (item.status !== 'active' || !item.recurring_enrollment) {
          return
        }
        if (new Date(item.class_start).getTime() <= now) {
          return
        }
        futureMap[item.recurring_enrollment] = (futureMap[item.recurring_enrollment] || 0) + 1
      })
      setItems(data)
      setFutureByRecurring(futureMap)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus recurrencias.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const options = useMemo(() => extractStudentRecurringOptions(items), [items])
  const filteredItems = useMemo(() => applyStudentRecurringFilters(items, filters), [items, filters])
  const kpis = useMemo(() => calculateRecurringKpis(filteredItems), [filteredItems])
  const policyMessage = items.find((item) => item.manage_policy_message)?.manage_policy_message

  const toggle = async (row) => {
    setWorkingId(row.id)
    setError('')
    setNotice('')
    try {
      await recurringEnrollmentsApi.update(row.id, { is_active: !row.is_active })
      await loadData()
      setNotice(row.is_active ? 'Recurrencia pausada.' : 'Recurrencia reactivada.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo actualizar la recurrencia.'))
    } finally {
      setWorkingId(null)
    }
  }

  const removeRecurring = async (row) => {
    setWorkingId(row.id)
    setError('')
    setNotice('')
    try {
      await recurringEnrollmentsApi.remove(row.id)
      await loadData()
      setNotice('Recurrencia eliminada. Se cancelaron sus reservas futuras asociadas.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo eliminar la recurrencia.'))
    } finally {
      setWorkingId(null)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'template_name', label: 'Serie', render: (row) => row.template_name || `Serie #${row.class_template}` },
      { key: 'template_branch_name', label: 'Sucursal', render: (row) => row.template_branch_name || '-' },
      { key: 'template_teacher_name', label: 'Profesor', render: (row) => row.template_teacher_name || '-' },
      { key: 'template_discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.template_discipline_name} /> },
      { key: 'template_weekday', label: 'Dia', render: (row) => weekdayLabels[row.template_weekday] || '-' },
      { key: 'template_start_time', label: 'Inicio', render: (row) => row.template_start_time?.slice(0, 5) || '-' },
      { key: 'template_end_time', label: 'Termino', render: (row) => row.template_end_time?.slice(0, 5) || '-' },
      { key: 'start_date', label: 'Desde', render: (row) => formatDate(row.start_date) },
      { key: 'end_date', label: 'Hasta', render: (row) => formatDate(row.end_date) },
      { key: 'next_class_start', label: 'Proxima clase', render: (row) => formatDateTime(row.next_class_start) },
      { key: 'next_reservations', label: 'Proximas reservas', render: (row) => futureByRecurring[row.id] || 0 },
      { key: 'is_active', label: 'Estado', render: (row) => <ValueBadge kind="template_status" value={row.is_active ? 'active' : 'paused'} /> },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <div className="space-y-1">
            <button
              type="button"
              disabled={!row.can_manage_now || workingId === row.id}
              onClick={() => toggle(row)}
              className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
            >
              {workingId === row.id ? 'Actualizando...' : row.is_active ? 'Pausar recurrencia' : 'Reactivar recurrencia'}
            </button>
            <button
              type="button"
              disabled={!row.can_manage_now || workingId === row.id}
              onClick={() => removeRecurring(row)}
              className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 disabled:opacity-60"
            >
              {workingId === row.id ? 'Eliminando...' : 'Quitar recurrencia completa'}
            </button>
            {!row.can_manage_now && row.manage_block_reason ? <p className="text-[11px] text-brand-muted">{row.manage_block_reason}</p> : null}
          </div>
        ),
      },
    ],
    [futureByRecurring, workingId],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader title="Student · Mis recurrencias" subtitle="Activa, pausa o reactiva tus series semanales de forma segura." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}
      {policyMessage ? <p className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs text-brand-muted">{policyMessage}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Total recurrencias</p>
            <p className="text-xl font-semibold">{kpis.total}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Activas</p>
            <p className="text-xl font-semibold">{kpis.active}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Pausadas</p>
            <p className="text-xl font-semibold">{kpis.paused}</p>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <FilterDropdown label="Profesor" value={filters.teacher} options={options.teacherOptions} onChange={(value) => setFilters((prev) => ({ ...prev, teacher: value }))} />
          <FilterDropdown label="Disciplina" value={filters.discipline} options={options.disciplineOptions} onChange={(value) => setFilters((prev) => ({ ...prev, discipline: value }))} />
          <FilterDropdown label="Estado" value={filters.status} options={statusOptions} onChange={(value) => setFilters((prev) => ({ ...prev, status: value }))} />
          <button
            type="button"
            onClick={() => setFilters(initialFilters)}
            className="rounded-lg border border-brand-line px-3 py-2 text-xs text-brand-muted transition hover:text-brand-white"
          >
            Limpiar filtros
          </button>
        </div>
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={filteredItems} loading={loading} defaultSort={{ key: 'next_class_start', direction: 'asc' }} />
      </section>
    </div>
  )
}
