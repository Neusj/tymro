import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  freezePlanMembership,
  getStudentOverview,
  studentOverviewDetailsApi,
  unfreezePlanMembership,
  usersApi,
} from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import ValueBadge from '../components/ui/ValueBadge'
import { extractApiErrorMessage } from '../utils/apiErrors'
import { formatDate, todayLocalISO } from '../utils/format'
import { studentSubjectRoleParam } from '../utils/roles'

const PAGE_SIZE = 100
const STUDENT_SEARCH_DEBOUNCE_MS = 300
const STUDENT_SEARCH_MIN_CHARS = 2
const STUDENT_SEARCH_LIMIT = 15
const PERIOD_OPTIONS = [
  { value: '30d', label: '30 dias' },
  { value: '90d', label: '90 dias' },
  { value: '6m', label: '6 meses' },
  { value: '1y', label: '1 ano' },
  { value: 'custom', label: 'Personalizado' },
]
const WEEKDAY_LABELS = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']
const EMPTY_SECTION = { items: [], count: 0, page: 1, page_size: PAGE_SIZE, has_next: false, has_previous: false }
const freezeInitialForm = { start_date: '', planned_end_date: '', reason: '' }

const PAYMENT_STATUS_LABELS = { paid: 'Pagado', unpaid: 'Impago', free: 'Gratuito' }
const PAYMENT_STATUS_CLASSES = {
  paid: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  unpaid: 'border-brand-red/40 bg-brand-red/10 text-red-200',
  free: 'border-brand-blue/40 bg-brand-blue/10 text-blue-200',
}
const ENROLLMENT_FEE_LABELS = {
  waived: 'Sin matricula',
  paid: 'Matricula pagada',
  pending: 'Matricula pendiente',
  overdue: 'Matricula vencida',
}

function toList(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.results)) return data.results
  return []
}

function studentName(item = {}) {
  return item.name || `${item.first_name || ''} ${item.last_name || ''}`.trim() || item.username || 'Alumno'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('es-CL', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatTime(value) {
  return value ? value.slice(0, 5) : '-'
}

function addDaysInput(value, days) {
  const base = value ? new Date(`${value}T00:00:00`) : new Date()
  base.setDate(base.getDate() + days)
  return base.toISOString().slice(0, 10)
}

function daysBetween(startDate, endDate) {
  if (!startDate || !endDate) return 0
  const start = new Date(`${startDate}T00:00:00`)
  const end = new Date(`${endDate}T00:00:00`)
  return Math.max(Math.round((end.getTime() - start.getTime()) / 86400000), 0)
}

function addDaysToDate(value, days) {
  if (!value) return ''
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

function PaymentStatusBadge({ status }) {
  if (!status) return null
  const className = PAYMENT_STATUS_CLASSES[status] || 'border-brand-line bg-black/20 text-brand-muted'
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      {PAYMENT_STATUS_LABELS[status] || status}
    </span>
  )
}

function EnrollmentFeeNote({ enrollmentFeeStatus }) {
  const status = enrollmentFeeStatus?.status
  if (!status || status === 'waived') return null
  return <span className="text-[11px] text-brand-dim">{ENROLLMENT_FEE_LABELS[status] || status}</span>
}

function displayMembershipStatusLabel(membership) {
  return membership?.active_freeze ? 'Congelada' : membership?.validity_status_label
}

function displayMembershipStatusLevel(membership) {
  return membership?.active_freeze ? 'warning' : membership?.expiry_alert_level
}

function isVisibleActiveMembership(membership) {
  return Boolean(membership?.active_freeze) || ['active', 'frozen'].includes(membership?.validity_status)
}

function DetailButton({ children, onClick, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="min-h-9 rounded-lg border border-brand-line px-3 py-1.5 text-xs font-semibold text-brand-white transition hover:border-brand-orange disabled:opacity-50"
    >
      {children}
    </button>
  )
}

function DashboardSection({ title, action, children }) {
  return (
    <section className="border-t border-brand-line py-5 first:border-t-0 first:pt-0">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-brand-white">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function BreakdownList({ items = [], emptyLabel = 'Sin datos' }) {
  if (!items.length) {
    return <p className="text-sm text-brand-muted">{emptyLabel}</p>
  }
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={`${item.discipline_id || 'none'}-${item.discipline_name || 'none'}`} className="flex items-center justify-between gap-3 text-sm">
          <span className="truncate text-brand-muted">{item.discipline_name || 'Sin disciplina'}</span>
          <span className="font-semibold text-brand-white">{item.total}</span>
        </div>
      ))}
    </div>
  )
}

function MembershipSummaryCard({ membership, onFreeze, onLiberate, working }) {
  const remaining = membership.unlimited_classes ? 'Ilimitadas' : `${membership.remaining_classes ?? 0} disponibles`
  return (
    <article className="rounded-lg border border-brand-line bg-black/20 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-brand-white">{membership.plan_name || 'Plan'}</p>
          <p className="mt-1 text-xs text-brand-muted">{remaining}</p>
          <p className="text-xs text-brand-dim">Hasta {formatDate(membership.end_date)}</p>
        </div>
        <PlanAlertBadge level={displayMembershipStatusLevel(membership)} message={displayMembershipStatusLabel(membership)} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <PaymentStatusBadge status={membership.payment_status} />
        <EnrollmentFeeNote enrollmentFeeStatus={membership.enrollment_fee_status} />
      </div>
      <div className="mt-3 flex flex-wrap gap-2 border-t border-brand-line pt-3">
        {membership.active_freeze ? (
          <button
            type="button"
            disabled={working}
            onClick={() => onLiberate(membership)}
            className="rounded-lg border border-amber-400/50 px-3 py-1.5 text-xs font-semibold text-amber-100 disabled:opacity-50"
          >
            Liberar
          </button>
        ) : (
          <button
            type="button"
            disabled={working || membership.validity_status !== 'active'}
            onClick={() => onFreeze(membership)}
            className="rounded-lg border border-brand-line px-3 py-1.5 text-xs font-semibold text-brand-white disabled:opacity-50"
          >
            Congelar
          </button>
        )}
      </div>
    </article>
  )
}

function StudentAutocomplete({ onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const requestIdRef = useRef(0)
  const lastSubmittedRef = useRef('')
  const trimmedQuery = query.trim()
  const canSearch = trimmedQuery.length >= STUDENT_SEARCH_MIN_CHARS

  useEffect(() => {
    if (!canSearch) {
      requestIdRef.current += 1
      lastSubmittedRef.current = ''
      setResults([])
      setLoading(false)
      setError('')
      return
    }

    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setOpen(true)
    setLoading(true)
    setError('')

    const timer = window.setTimeout(() => {
      if (lastSubmittedRef.current === trimmedQuery) {
        setLoading(false)
        return
      }
      lastSubmittedRef.current = trimmedQuery
      usersApi
        .list({
          role: studentSubjectRoleParam,
          search: trimmedQuery,
          limit: STUDENT_SEARCH_LIMIT,
        })
        .then((response) => {
          if (requestIdRef.current !== requestId) return
          setResults(toList(response))
        })
        .catch((apiError) => {
          if (requestIdRef.current !== requestId) return
          setResults([])
          setError(extractApiErrorMessage(apiError, 'No se pudo buscar alumnos.'))
        })
        .finally(() => {
          if (requestIdRef.current === requestId) {
            setLoading(false)
          }
        })
    }, STUDENT_SEARCH_DEBOUNCE_MS)

    return () => {
      window.clearTimeout(timer)
    }
  }, [canSearch, trimmedQuery])

  const pickStudent = (student) => {
    onSelect(student)
    setQuery('')
    setResults([])
    setError('')
    setOpen(false)
  }

  return (
    <div className="space-y-2">
      <label className="block space-y-1 text-sm">
        <span>Buscar alumno</span>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          placeholder="Nombre, apellido o email"
          className="field"
          autoComplete="off"
        />
      </label>
      {open && query ? (
        <div className="overflow-hidden rounded-xl border border-brand-line bg-brand-panel shadow-float">
          {!canSearch ? (
            <p className="px-3 py-2 text-xs text-brand-muted">Escribe al menos {STUDENT_SEARCH_MIN_CHARS} caracteres.</p>
          ) : loading ? (
            <p className="px-3 py-2 text-xs text-brand-muted">Buscando...</p>
          ) : error ? (
            <p className="px-3 py-2 text-xs text-red-200">{error}</p>
          ) : results.length === 0 ? (
            <p className="px-3 py-2 text-xs text-brand-muted">Sin resultados</p>
          ) : (
            <ul className="max-h-72 overflow-y-auto py-1">
              {results.map((student) => (
                <li key={student.id}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => pickStudent(student)}
                    className="block w-full px-3 py-2 text-left transition hover:bg-brand-soft focus:bg-brand-soft focus:outline-none"
                  >
                    <span className="block truncate text-sm font-semibold text-brand-white">{studentName(student)}</span>
                    <span className="block truncate text-xs text-brand-muted">{student.email || 'Sin email'}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}

function ClassPreview({ item }) {
  const classInfo = item.class || {}
  return (
    <article className="rounded-lg border border-brand-line bg-black/20 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-brand-white">{classInfo.name || 'Clase'}</p>
          <p className="text-xs text-brand-muted">{formatDateTime(classInfo.start_datetime)}</p>
          <p className="text-xs text-brand-dim">{classInfo.discipline_name || 'Sin disciplina'}</p>
        </div>
        {item.status ? <ValueBadge kind="enrollment_status" value={item.status} /> : null}
      </div>
    </article>
  )
}

function RecurringPreview({ item }) {
  const template = item.class_template || {}
  return (
    <article className="rounded-lg border border-brand-line bg-black/20 p-3">
      <p className="truncate text-sm font-semibold text-brand-white">{template.name || 'Reserva semanal'}</p>
      <p className="text-xs text-brand-muted">
        {template.discipline_name || 'Sin disciplina'} - {WEEKDAY_LABELS[template.weekday] || 'Dia'} - {formatTime(template.start_time)}
      </p>
    </article>
  )
}

function normalizeDetailRows(type, rows = []) {
  return rows.map((item) => {
    if (type === 'memberships') {
      return {
        id: item.id,
        plan: item.plan_name || 'Plan',
        vigencia: `${formatDate(item.start_date)} - ${formatDate(item.end_date)}`,
        disponibles: item.unlimited_classes ? 'Ilimitadas' : item.remaining_classes ?? 0,
        estado: displayMembershipStatusLabel(item) || item.validity_status || '-',
        pago: PAYMENT_STATUS_LABELS[item.payment_status] || item.payment_status || '-',
        matricula: ENROLLMENT_FEE_LABELS[item.enrollment_fee_status?.status] || item.enrollment_fee_status?.status || '-',
        raw: item,
      }
    }
    if (type === 'attendance') {
      return {
        id: item.id,
        clase: item.class?.name || 'Clase',
        fecha: formatDateTime(item.marked_at),
        disciplina: item.class?.discipline_name || 'Sin disciplina',
        estado: item.status,
        fuente: item.source || '-',
        marcado_por: item.marked_by_name || '-',
        raw: item,
      }
    }
    if (type === 'consumption') {
      return {
        id: item.id,
        clase: item.class?.name || 'Clase',
        fecha: formatDateTime(item.consumed_at),
        disciplina: item.class?.discipline_name || 'Sin disciplina',
        plan: item.plan_name || 'Sin plan',
        sede: item.branch_name || 'Sin sucursal',
        raw: item,
      }
    }
    if (type === 'recurringReservations') {
      const template = item.class_template || {}
      return {
        id: item.id,
        reserva: template.name || 'Reserva semanal',
        disciplina: template.discipline_name || 'Sin disciplina',
        dia: WEEKDAY_LABELS[template.weekday] || 'Dia',
        hora: `${formatTime(template.start_time)} - ${formatTime(template.end_time)}`,
        vigencia: `${formatDate(item.start_date)} - ${item.end_date ? formatDate(item.end_date) : 'Sin termino'}`,
        plan: item.plan_name || 'Sin plan fijado',
        raw: item,
      }
    }
    return {
      id: item.id,
      clase: item.class?.name || 'Clase',
      fecha: formatDateTime(item.class?.start_datetime),
      disciplina: item.class?.discipline_name || 'Sin disciplina',
      estado: item.status,
      tipo: item.is_trial ? 'Clase de prueba' : 'Reserva',
      plan: item.plan_name || 'Sin plan',
      raw: item,
    }
  })
}

function detailColumns(type, actions = {}) {
  if (type === 'memberships') {
    return [
      { key: 'plan', label: 'Plan', mobile: 'title' },
      { key: 'estado', label: 'Estado', mobile: 'meta' },
      { key: 'vigencia', label: 'Vigencia', mobile: 'secondary' },
      { key: 'disponibles', label: 'Disponibles', mobile: 'secondary' },
      { key: 'pago', label: 'Pago' },
      { key: 'matricula', label: 'Matricula' },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => {
          const membership = row.raw || {}
          return membership.active_freeze ? (
            <button
              type="button"
              disabled={actions.working}
              onClick={() => actions.onLiberate?.(membership)}
              className="rounded border border-amber-400/50 px-2 py-1 text-xs text-amber-100 disabled:opacity-50"
            >
              Liberar
            </button>
          ) : (
            <button
              type="button"
              disabled={actions.working || membership.validity_status !== 'active'}
              onClick={() => actions.onFreeze?.(membership)}
              className="rounded border border-brand-line px-2 py-1 text-xs text-brand-white disabled:opacity-50"
            >
              Congelar
            </button>
          )
        },
      },
    ]
  }
  if (type === 'attendance') {
    return [
      { key: 'clase', label: 'Clase', mobile: 'title' },
      {
        key: 'estado',
        label: 'Estado',
        mobile: 'meta',
        render: (row) => <ValueBadge kind="attendance_status" value={row.estado} />,
        sortAccessor: (row) => row.estado,
      },
      { key: 'fecha', label: 'Fecha', mobile: 'secondary' },
      { key: 'disciplina', label: 'Disciplina', mobile: 'secondary' },
      { key: 'fuente', label: 'Fuente' },
      { key: 'marcado_por', label: 'Marcado por' },
    ]
  }
  if (type === 'consumption') {
    return [
      { key: 'clase', label: 'Clase', mobile: 'title' },
      { key: 'fecha', label: 'Fecha', mobile: 'secondary' },
      { key: 'disciplina', label: 'Disciplina', mobile: 'secondary' },
      { key: 'plan', label: 'Plan' },
      { key: 'sede', label: 'Sede' },
    ]
  }
  if (type === 'recurringReservations') {
    return [
      { key: 'reserva', label: 'Reserva semanal', mobile: 'title' },
      { key: 'disciplina', label: 'Disciplina', mobile: 'secondary' },
      { key: 'dia', label: 'Dia', mobile: 'secondary' },
      { key: 'hora', label: 'Hora' },
      { key: 'vigencia', label: 'Vigencia' },
      { key: 'plan', label: 'Plan' },
    ]
  }
  return [
    { key: 'clase', label: 'Clase', mobile: 'title' },
    {
      key: 'estado',
      label: 'Estado',
      mobile: 'meta',
      render: (row) => <ValueBadge kind="enrollment_status" value={row.estado} />,
      sortAccessor: (row) => row.estado,
    },
    { key: 'fecha', label: 'Fecha', mobile: 'secondary' },
    { key: 'disciplina', label: 'Disciplina', mobile: 'secondary' },
    { key: 'tipo', label: 'Tipo' },
    { key: 'plan', label: 'Plan' },
  ]
}

function buildFallbackSummary(data) {
  const memberships = data?.memberships || []
  const activeItems = memberships.filter(isVisibleActiveMembership)
  return {
    period: { key: '30d', label: 'Ultimos 30 dias', start_date: null, end_date: null },
    memberships: {
      active_count: activeItems.length,
      active_items: activeItems,
      historical_count: Math.max(memberships.length - activeItems.length, 0),
    },
    reservations: {
      future_active_total: data?.reservations?.items?.length || 0,
      by_discipline: [],
      upcoming: (data?.reservations?.items || []).slice(0, 3),
    },
    consumption: { total: data?.consumption?.items?.length || 0, by_discipline: [] },
    attendance: {
      present: 0,
      absences: 0,
      attendance_rate: null,
      denominator: 0,
      formula: 'present / (present + absent + no_show)',
      by_status: {},
      by_discipline: [],
    },
    recurring_reservations: {
      active_total: data?.recurring_enrollments?.length || 0,
      preview: (data?.recurring_enrollments || []).slice(0, 3),
    },
  }
}

const DETAIL_TITLES = {
  reservations: 'Reservas',
  attendance: 'Asistencia',
  consumption: 'Consumo',
  memberships: 'Historial de membresias',
  recurringReservations: 'Reservas semanales automaticas',
}

export default function GymAdminStudentOverviewPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const studentId = searchParams.get('student_id') || ''
  const [selectedStudentPreview, setSelectedStudentPreview] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [workingMembership, setWorkingMembership] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [period, setPeriod] = useState('30d')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState(todayLocalISO())
  const [detail, setDetail] = useState({ type: '', loading: false, error: '', data: EMPTY_SECTION })
  const [freezing, setFreezing] = useState(null)
  const [freezeForm, setFreezeForm] = useState(freezeInitialForm)
  const [liberating, setLiberating] = useState(null)
  const detailPanelRef = useRef(null)

  const overviewParams = useMemo(() => {
    const params = { period }
    if (period === 'custom') {
      if (customStart) params.start_date = customStart
      if (customEnd) params.end_date = customEnd
    }
    return params
  }, [period, customStart, customEnd])

  const load = useCallback(async (id, params) => {
    try {
      const response = await getStudentOverview(id, params)
      setData(response)
      setError('')
    } catch (apiError) {
      setData(null)
      setError(extractApiErrorMessage(apiError, 'No se pudo cargar la vista integral del alumno.'))
    }
  }, [])

  useEffect(() => {
    setDetail({ type: '', loading: false, error: '', data: EMPTY_SECTION })
    if (!studentId) {
      setSelectedStudentPreview(null)
      setData(null)
      setError('')
      return
    }
    setLoading(true)
    load(studentId, overviewParams).finally(() => setLoading(false))
  }, [studentId, overviewParams, load])

  const selectStudent = (student) => {
    const value = student?.id ? String(student.id) : ''
    setSelectedStudentPreview(student || null)
    const next = new URLSearchParams(searchParams)
    if (value) next.set('student_id', value)
    else next.delete('student_id')
    setSearchParams(next)
  }

  const currentSummary = data?.summary || buildFallbackSummary(data)
  const selectedStudent = data?.student || selectedStudentPreview
  useEffect(() => {
    if (!detail.type || !detailPanelRef.current) return
    window.setTimeout(() => {
      if (typeof detailPanelRef.current?.scrollIntoView === 'function') {
        detailPanelRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      detailPanelRef.current?.focus({ preventScroll: true })
    }, 0)
  }, [detail.type])

  const loadDetail = async (type, page = 1) => {
    if (!studentId) return
    const params = { page, page_size: PAGE_SIZE }
    if (type === 'attendance' || type === 'consumption') {
      if (currentSummary.period?.start_date) params.date_from = currentSummary.period.start_date
      if (currentSummary.period?.end_date) params.date_to = currentSummary.period.end_date
    }
    if (type === 'memberships') {
      params.status = 'historical'
    }
    if (type === 'recurringReservations') {
      params.is_active = 'true'
    }

    setDetail((prev) => ({ ...prev, type, loading: true, error: '' }))
    try {
      const response = await studentOverviewDetailsApi[type](studentId, params)
      setDetail({ type, loading: false, error: '', data: response })
    } catch (apiError) {
      setDetail({
        type,
        loading: false,
        error: extractApiErrorMessage(apiError, 'No se pudo cargar el detalle.'),
        data: EMPTY_SECTION,
      })
    }
  }

  const closeDetail = () => setDetail({ type: '', loading: false, error: '', data: EMPTY_SECTION })
  const activeMemberships = currentSummary.memberships.active_items || []
  const refreshMembershipData = async () => {
    await load(studentId, overviewParams)
    if (detail.type === 'memberships') {
      await loadDetail('memberships', detail.data.page || 1)
    }
  }
  const openFreeze = (membership) => {
    const start = todayLocalISO()
    setFreezing(membership)
    setFreezeForm({ start_date: start, planned_end_date: addDaysInput(start, 1), reason: '' })
    setError('')
    setNotice('')
  }
  const saveFreeze = async (event) => {
    event.preventDefault()
    if (!freezing) return
    if (!freezeForm.reason.trim()) {
      setError('Indica el motivo del congelamiento.')
      return
    }
    setWorkingMembership(true)
    setError('')
    setNotice('')
    try {
      await freezePlanMembership(freezing.plan, freezing.id, {
        start_date: freezeForm.start_date,
        planned_end_date: freezeForm.planned_end_date,
        reason: freezeForm.reason.trim(),
      })
      setNotice('Membresia congelada.')
      setFreezing(null)
      await refreshMembershipData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo congelar la membresia.'))
    } finally {
      setWorkingMembership(false)
    }
  }
  const liberateMembership = async () => {
    if (!liberating) return
    setWorkingMembership(true)
    setError('')
    setNotice('')
    try {
      await unfreezePlanMembership(liberating.plan, liberating.id, { reason: 'Liberacion anticipada.' })
      setNotice('Membresia liberada.')
      setLiberating(null)
      await refreshMembershipData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo liberar la membresia.'))
    } finally {
      setWorkingMembership(false)
    }
  }
  const freezeDays = daysBetween(freezeForm.start_date, freezeForm.planned_end_date)
  const freezeProjectedEnd = freezing ? addDaysToDate(freezing.end_date, freezeDays) : ''

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Vista integral del alumno"
        subtitle="Estado actual, actividad del periodo y proximas reservas."
      />

      <main className="card-surface p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-xl font-semibold text-brand-white">{selectedStudent ? studentName(selectedStudent) : 'Elegir alumno'}</h1>
              {data ? (
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${data.student.is_active ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
                  {data.student.is_active ? 'Activo' : 'Inactivo'}
                </span>
              ) : null}
            </div>
            {selectedStudent ? (
              <p className="mt-1 text-sm text-brand-muted">
                {selectedStudent.email || 'Sin email'}{selectedStudent.phone ? ` - ${selectedStudent.phone}` : ''} - {selectedStudent.branch_name || 'Sin sucursal'}
              </p>
            ) : (
              <p className="mt-1 text-sm text-brand-muted">Selecciona un alumno para cargar su resumen.</p>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:w-[520px]">
            <StudentAutocomplete onSelect={selectStudent} />

            <label className="block space-y-1 text-sm">
              <span>Periodo</span>
              <select
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                className="field"
              >
                {PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {period === 'custom' ? (
          <div className="mt-4 grid gap-3 sm:max-w-lg sm:grid-cols-2">
            <label className="block space-y-1 text-sm">
              <span>Desde</span>
              <input
                type="date"
                value={customStart}
                onChange={(event) => setCustomStart(event.target.value)}
                className="field"
              />
            </label>
            <label className="block space-y-1 text-sm">
              <span>Hasta</span>
              <input
                type="date"
                value={customEnd}
                onChange={(event) => setCustomEnd(event.target.value)}
                className="field"
              />
            </label>
          </div>
        ) : null}

        {!studentId ? (
          <div className="mt-5">
            <EmptyState title="Sin alumno seleccionado" description="Elegir un alumno en el selector para ver su vista integral." />
          </div>
        ) : loading ? (
          <div className="mt-5 space-y-3">
            <div className="h-20 animate-pulse rounded-xl bg-brand-line/40" />
            <div className="h-20 animate-pulse rounded-xl bg-brand-line/30" />
          </div>
        ) : error ? (
          <p className="mt-5 rounded-xl border border-brand-red/50 bg-brand-red/10 px-4 py-3 text-sm text-red-200">{error}</p>
        ) : data ? (
          <div className="mt-5">
            {notice ? <p className="mb-4 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">{notice}</p> : null}
            <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                <p className="text-xs text-brand-muted">Membresias activas</p>
                <p className="text-2xl font-semibold text-brand-white">{currentSummary.memberships.active_count}</p>
              </div>
              <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                <p className="text-xs text-brand-muted">Reservas futuras</p>
                <p className="text-2xl font-semibold text-brand-white">{currentSummary.reservations.future_active_total}</p>
              </div>
              <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                <p className="text-xs text-brand-muted">Clases consumidas</p>
                <p className="text-2xl font-semibold text-brand-white">{currentSummary.consumption.total}</p>
              </div>
              <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                <p className="text-xs text-brand-muted">Asistencia</p>
                <p className="text-2xl font-semibold text-brand-white">
                  {currentSummary.attendance.attendance_rate == null ? '-' : `${currentSummary.attendance.attendance_rate}%`}
                </p>
              </div>
            </div>

            <DashboardSection
              title="Membresias activas"
              action={<DetailButton onClick={() => loadDetail('memberships')}>Ver historial</DetailButton>}
            >
              {activeMemberships.length ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {activeMemberships.map((membership) => (
                    <MembershipSummaryCard
                      key={membership.id}
                      membership={membership}
                      working={workingMembership}
                      onFreeze={openFreeze}
                      onLiberate={setLiberating}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState title="Sin membresias activas" description="Este alumno no tiene planes vigentes para mostrar." />
              )}
              <p className="mt-3 text-sm text-brand-muted">{currentSummary.memberships.historical_count} membresias anteriores</p>
            </DashboardSection>

            <DashboardSection
              title="Reservas"
              action={<DetailButton onClick={() => loadDetail('reservations')}>Ver reservas</DetailButton>}
            >
              <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
                <div>
                  <p className="text-sm text-brand-muted">Reservas futuras activas</p>
                  <p className="text-3xl font-semibold text-brand-white">{currentSummary.reservations.future_active_total}</p>
                  <div className="mt-3">
                    <BreakdownList items={currentSummary.reservations.by_discipline} />
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {(currentSummary.reservations.upcoming || []).length ? (
                    currentSummary.reservations.upcoming.map((item) => <ClassPreview key={item.id} item={item} />)
                  ) : (
                    <p className="text-sm text-brand-muted">Sin proximas reservas.</p>
                  )}
                </div>
              </div>
            </DashboardSection>

            <DashboardSection
              title="Consumo"
              action={<DetailButton onClick={() => loadDetail('consumption')}>Ver detalle</DetailButton>}
            >
              <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
                <div>
                  <p className="text-sm text-brand-muted">{currentSummary.period?.label || 'Periodo'}</p>
                  <p className="text-3xl font-semibold text-brand-white">{currentSummary.consumption.total}</p>
                  <p className="text-xs text-brand-dim">clases consumidas</p>
                </div>
                <BreakdownList items={currentSummary.consumption.by_discipline} />
              </div>
            </DashboardSection>

            <DashboardSection
              title="Asistencia"
              action={<DetailButton onClick={() => loadDetail('attendance')}>Ver detalle</DetailButton>}
            >
              <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_1fr]">
                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                    <p className="text-xs text-brand-muted">Presentes</p>
                    <p className="text-xl font-semibold text-brand-white">{currentSummary.attendance.present}</p>
                  </div>
                  <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                    <p className="text-xs text-brand-muted">Ausencias</p>
                    <p className="text-xl font-semibold text-brand-white">{currentSummary.attendance.absences}</p>
                  </div>
                  <div className="rounded-lg border border-brand-line bg-black/20 p-3">
                    <p className="text-xs text-brand-muted">Porcentaje</p>
                    <p className="text-xl font-semibold text-brand-white">
                      {currentSummary.attendance.attendance_rate == null ? '-' : `${currentSummary.attendance.attendance_rate}%`}
                    </p>
                  </div>
                </div>
                <div>
                  <BreakdownList items={currentSummary.attendance.by_discipline} />
                  <p className="mt-3 text-xs text-brand-dim">Formula: {currentSummary.attendance.formula}</p>
                </div>
              </div>
            </DashboardSection>

            <DashboardSection
              title="Reservas semanales automaticas"
              action={<DetailButton onClick={() => loadDetail('recurringReservations')}>Ver</DetailButton>}
            >
              <p className="text-sm text-brand-muted">
                {currentSummary.recurring_reservations.active_total} activas
              </p>
              {(currentSummary.recurring_reservations.preview || []).length ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {currentSummary.recurring_reservations.preview.map((item) => (
                    <RecurringPreview key={item.id} item={item} />
                  ))}
                </div>
              ) : null}
            </DashboardSection>
          </div>
        ) : null}
      </main>

      {detail.type ? (
        <section
          ref={detailPanelRef}
          tabIndex={-1}
          className="card-surface scroll-mt-4 p-4 outline-none ring-brand-blue/40 focus-visible:ring-2 sm:p-5"
        >
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-brand-white">{DETAIL_TITLES[detail.type]}</h2>
              <p className="text-sm text-brand-muted">{detail.data.count || 0} registros</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <DetailButton disabled={detail.loading || !detail.data.has_previous} onClick={() => loadDetail(detail.type, detail.data.page - 1)}>Anterior</DetailButton>
              <DetailButton disabled={detail.loading || !detail.data.has_next} onClick={() => loadDetail(detail.type, detail.data.page + 1)}>Siguiente</DetailButton>
              <DetailButton onClick={closeDetail}>Cerrar</DetailButton>
            </div>
          </div>
          {detail.loading ? (
            <div className="h-24 animate-pulse rounded-xl bg-brand-line/30" />
          ) : detail.error ? (
            <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 px-4 py-3 text-sm text-red-200">{detail.error}</p>
          ) : (
            <DataTable
              columns={detailColumns(detail.type, {
                working: workingMembership,
                onFreeze: openFreeze,
                onLiberate: setLiberating,
              })}
              data={normalizeDetailRows(detail.type, detail.data.items || [])}
              maxBodyHeight="520px"
              defaultSort={{ key: detail.type === 'memberships' ? 'vigencia' : 'fecha', direction: 'desc' }}
            />
          )}
        </section>
      ) : null}

      <FormModal
        open={Boolean(freezing)}
        title={`Congelar membresia${freezing ? ` - ${freezing.plan_name || 'Plan'}` : ''}`}
        size="md"
        closeDisabled={workingMembership}
        onClose={() => {
          setFreezing(null)
          setError('')
        }}
      >
        <form onSubmit={saveFreeze} className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="min-w-0 space-y-1 text-sm">
              <span>Inicio</span>
              <input
                required
                type="date"
                disabled={workingMembership}
                value={freezeForm.start_date}
                onChange={(event) => {
                  const nextStart = event.target.value
                  setFreezeForm((prev) => ({
                    ...prev,
                    start_date: nextStart,
                    planned_end_date: prev.planned_end_date && prev.planned_end_date > nextStart
                      ? prev.planned_end_date
                      : addDaysInput(nextStart, 1),
                  }))
                }}
                className="field"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Termino</span>
              <input
                required
                type="date"
                disabled={workingMembership}
                value={freezeForm.planned_end_date}
                onChange={(event) => setFreezeForm((prev) => ({ ...prev, planned_end_date: event.target.value }))}
                className="field"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm md:col-span-2">
              <span>Motivo</span>
              <textarea
                required
                rows={3}
                disabled={workingMembership}
                value={freezeForm.reason}
                onChange={(event) => setFreezeForm((prev) => ({ ...prev, reason: event.target.value }))}
                className="field"
              />
            </label>
          </div>
          <div className="rounded-lg border border-brand-line bg-black/20 p-3 text-sm">
            Esta membresia se congelara por {freezeDays} dia(s).
            {freezeProjectedEnd ? <span className="block text-brand-muted">Nuevo vencimiento previsto: {formatDate(freezeProjectedEnd)}</span> : null}
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" disabled={workingMembership} onClick={() => setFreezing(null)} className="rounded-lg border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white disabled:opacity-60">
              Cancelar
            </button>
            <button type="submit" disabled={workingMembership || freezeDays <= 0} className="rounded-lg bg-brand-blue px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {workingMembership ? 'Guardando...' : 'Congelar membresia'}
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(liberating)}
        title="Liberar membresia"
        description={`Se cerrara el congelamiento de ${liberating?.plan_name || 'esta membresia'}.`}
        confirmLabel="Liberar"
        loading={workingMembership}
        onCancel={() => setLiberating(null)}
        onConfirm={liberateMembership}
      />
    </div>
  )
}
