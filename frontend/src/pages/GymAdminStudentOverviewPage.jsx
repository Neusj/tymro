import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getStudentOverview, usersApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import KpiStrip from '../components/KpiStrip'
import SectionCard from '../components/SectionCard'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import ValueBadge from '../components/ui/ValueBadge'
import { extractApiErrorMessage } from '../utils/apiErrors'
import { formatDate } from '../utils/format'
import { studentSubjectRoleParam } from '../utils/roles'

function toList(data) {
  if (Array.isArray(data)) {
    return data
  }
  if (Array.isArray(data?.results)) {
    return data.results
  }
  return []
}

function studentLabel(item) {
  const fullName = `${item.first_name || ''} ${item.last_name || ''}`.trim() || item.username
  return item.email ? `${fullName} · ${item.email}` : fullName
}

// El backend manda DateTimeField como ISO con offset; `formatDate` de utils/format.js está
// pensado para DateField puro ('YYYY-MM-DD') y le recorta la hora. Espejo local del patrón
// que ya usan GymAdminClassDetailPage/GymAdminClassesPage para start_datetime/marked_at.
function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  return date.toLocaleString('es-CL', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatTime(value) {
  if (!value) {
    return '-'
  }
  return value.slice(0, 5)
}

const WEEKDAY_LABELS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

// `payment_status` (paid/unpaid/free) es del MISMO eje que `validity_status`, pero no tiene
// badge propio en la UI todavía (PlanAlertBadge pinta severidad de VIGENCIA, no de pago). El
// backend no manda ni nivel ni color para este eje —sale directo de `describe_student_plan`,
// sin presentación— así que el mapeo de color es puramente cosmético y vive acá, igual que
// `PlanAlertBadge` documenta que "lo único que queda del lado del cliente es el color".
const PAYMENT_STATUS_LABELS = { paid: 'Pagado', unpaid: 'Impago', free: 'Gratuito' }
const PAYMENT_STATUS_CLASSES = {
  paid: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  unpaid: 'border-brand-red/40 bg-brand-red/10 text-red-200',
  free: 'border-brand-blue/40 bg-brand-blue/10 text-blue-200',
}

function PaymentStatusBadge({ status }) {
  if (!status) {
    return null
  }
  const className = PAYMENT_STATUS_CLASSES[status] || 'border-brand-line bg-black/20 text-brand-muted'
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      {PAYMENT_STATUS_LABELS[status] || status}
    </span>
  )
}

const ENROLLMENT_FEE_LABELS = { waived: 'Sin matrícula', paid: 'Matrícula pagada', pending: 'Matrícula pendiente', overdue: 'Matrícula vencida' }

function EnrollmentFeeNote({ enrollmentFeeStatus }) {
  const status = enrollmentFeeStatus?.status
  if (!status || status === 'waived') {
    return null
  }
  return <p className="mt-1 text-[11px] text-brand-dim">{ENROLLMENT_FEE_LABELS[status] || status}</p>
}

function ClassCardHeader({ classInfo, statusBadge }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="truncate font-semibold text-brand-white">{classInfo?.name || 'Clase'}</p>
        <p className="text-xs text-brand-muted">{formatDateTime(classInfo?.start_datetime)}</p>
      </div>
      {statusBadge}
    </div>
  )
}

function MembershipCard({ membership }) {
  return (
    <div className="rounded-xl border border-brand-line bg-black/20 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold text-brand-white">{membership.plan_name || 'Plan'}</p>
          <p className="text-xs text-brand-muted">
            {formatDate(membership.start_date)} – {formatDate(membership.end_date)}
          </p>
        </div>
        <PlanAlertBadge level={membership.expiry_alert_level} message={membership.validity_status_label} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-brand-dim">Clases</p>
          <p className="text-brand-white">
            {membership.unlimited_classes ? 'Ilimitadas' : `${membership.classes_used ?? 0}/${membership.total_classes ?? 0}`}
          </p>
        </div>
        <div>
          <p className="text-brand-dim">Disponibles</p>
          <p className="text-brand-white">{membership.unlimited_classes ? '—' : membership.remaining_classes}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <PaymentStatusBadge status={membership.payment_status} />
        <PlanAlertBadge level={membership.expiry_alert_level} message={membership.expiry_alert_message} />
      </div>
      <EnrollmentFeeNote enrollmentFeeStatus={membership.enrollment_fee_status} />
    </div>
  )
}

function ConsumptionCard({ item }) {
  return (
    <div className="rounded-xl border border-brand-line bg-black/20 p-3">
      <ClassCardHeader classInfo={item.class} />
      <p className="mt-1.5 text-[11px] text-brand-dim">
        {item.plan_name || 'Sin plan asociado'} · {item.branch_name || 'Sin sucursal'}
      </p>
      <p className="mt-0.5 text-[11px] text-brand-dim">Consumida el {formatDateTime(item.consumed_at)}</p>
    </div>
  )
}

function AttendanceCard({ item }) {
  return (
    <div className="rounded-xl border border-brand-line bg-black/20 p-3">
      <ClassCardHeader classInfo={item.class} statusBadge={<ValueBadge kind="attendance_status" value={item.status} />} />
      <p className="mt-1.5 text-[11px] text-brand-dim">
        Marcada el {formatDateTime(item.marked_at)}{item.marked_by_name ? ` por ${item.marked_by_name}` : ''}
      </p>
    </div>
  )
}

function ReservationCard({ item }) {
  return (
    <div className="rounded-xl border border-brand-line bg-black/20 p-3">
      <ClassCardHeader classInfo={item.class} statusBadge={<ValueBadge kind="enrollment_status" value={item.status} />} />
      <p className="mt-1.5 text-[11px] text-brand-dim">
        {item.plan_name || 'Sin plan asociado'}{item.is_trial ? ' · Clase de prueba' : ''}
      </p>
    </div>
  )
}

function RecurringCard({ item }) {
  const template = item.class_template
  return (
    <div className="rounded-xl border border-brand-line bg-black/20 p-3">
      <p className="truncate font-semibold text-brand-white">{template?.name || 'Clase recurrente'}</p>
      <p className="text-xs text-brand-muted">
        {WEEKDAY_LABELS[template?.weekday] || 'Día no definido'} · {formatTime(template?.start_time)}–{formatTime(template?.end_time)}
      </p>
      <p className="mt-1.5 text-[11px] text-brand-dim">
        {template?.discipline_name || 'Sin disciplina'} · {template?.teacher_name || 'Sin profesor'}
      </p>
      <p className="mt-0.5 text-[11px] text-brand-dim">{item.plan_name ? `Plan fijado: ${item.plan_name}` : 'Sin plan fijado'}</p>
    </div>
  )
}

function ShowMoreButton({ loading, onClick }) {
  return (
    <div className="mt-3 flex justify-center">
      <button
        type="button"
        disabled={loading}
        onClick={onClick}
        className="min-h-10 rounded-lg border border-brand-line px-4 py-2 text-xs font-semibold text-brand-white transition hover:border-brand-orange disabled:opacity-50"
      >
        {loading ? 'Cargando…' : 'Ver más'}
      </button>
    </div>
  )
}

const INITIAL_LIMITS = { consumption_limit: 20, attendance_limit: 20, reservations_limit: 20 }
const LOAD_MORE_STEP = 20

const EMPTY_SECTION = { items: [], limit: 0, has_more: false }

export default function GymAdminStudentOverviewPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const studentId = searchParams.get('student_id') || ''

  // Picker de alumno (mismo patrón que `AssignPlanPage`): se carga UNA vez, independiente
  // de cuál alumno esté seleccionado. `studentSubjectRoleParam` = 'student,gym_admin', igual
  // que el selector de "Asignar plan" — el backend tampoco filtra el alumno objetivo por rol
  // (P4, doble identidad del gym_admin), así que el picker no puede ser más angosto que eso.
  const [students, setStudents] = useState([])
  const [studentsLoading, setStudentsLoading] = useState(true)
  const [studentsError, setStudentsError] = useState('')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [limits, setLimits] = useState(INITIAL_LIMITS)
  const [loadingMoreKey, setLoadingMoreKey] = useState('')

  useEffect(() => {
    usersApi
      .list({ role: studentSubjectRoleParam })
      .then((response) => setStudents(toList(response)))
      .catch((apiError) => setStudentsError(extractApiErrorMessage(apiError, 'No se pudo cargar la lista de alumnos.')))
      .finally(() => setStudentsLoading(false))
  }, [])

  const load = useCallback(async (id, queryLimits) => {
    try {
      const response = await getStudentOverview(id, queryLimits)
      setData(response)
      setError('')
    } catch (apiError) {
      setData(null)
      setError(extractApiErrorMessage(apiError, 'No se pudo cargar la vista integral del alumno.'))
    }
  }, [])

  useEffect(() => {
    if (!studentId) {
      setData(null)
      setError('')
      return
    }
    setLoading(true)
    setLimits(INITIAL_LIMITS)
    load(studentId, INITIAL_LIMITS).finally(() => setLoading(false))
  }, [studentId, load])

  const showMore = async (key) => {
    const nextLimits = { ...limits, [key]: limits[key] + LOAD_MORE_STEP }
    setLoadingMoreKey(key)
    setLimits(nextLimits)
    await load(studentId, nextLimits)
    setLoadingMoreKey('')
  }

  const selectStudent = (value) => {
    const next = new URLSearchParams(searchParams)
    if (value) {
      next.set('student_id', value)
    } else {
      next.delete('student_id')
    }
    setSearchParams(next)
  }

  const memberships = data?.memberships || []
  const consumption = data?.consumption || EMPTY_SECTION
  const attendance = data?.attendance || EMPTY_SECTION
  const reservations = data?.reservations || EMPTY_SECTION
  const recurringEnrollments = data?.recurring_enrollments || []
  const activeMembershipsCount = memberships.filter((membership) => membership.validity_status === 'active').length
  const kpiItems = [
    { label: 'Membresías', value: memberships.length },
    { label: 'Activas', value: activeMembershipsCount },
    { label: 'Recurrencias vigentes', value: recurringEnrollments.length },
    { label: 'Asistencias cargadas', value: attendance.items.length },
  ]

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Vista integral del alumno"
        subtitle="Membresías, consumo, asistencia, reservas y recurrencias en un solo lugar."
      />

      <SectionCard
        title={data ? data.student.name : 'Elegí un alumno'}
        subtitle={data ? `${data.student.email || 'Sin email'} · ${data.student.branch_name || 'Sin sucursal'}` : 'Buscá por nombre o email en el selector.'}
      >
        <label className="block space-y-1 text-sm">
          <span>Alumno</span>
          <select
            disabled={studentsLoading}
            value={studentId}
            onChange={(event) => selectStudent(event.target.value)}
            className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 sm:max-w-md"
          >
            <option value="">Seleccionar alumno</option>
            {students.map((item) => (
              <option key={item.id} value={item.id}>
                {studentLabel(item)}
              </option>
            ))}
          </select>
        </label>
        {studentsError ? <p className="mt-2 text-xs text-red-200">{studentsError}</p> : null}
      </SectionCard>

      {!studentId ? (
        <EmptyState title="Sin alumno seleccionado" description="Elegí un alumno en el selector de arriba para ver su vista integral." />
      ) : loading ? (
        <SectionCard title="Cargando">
          <div className="space-y-2">
            <div className="h-16 animate-pulse rounded-xl bg-brand-line/40" />
            <div className="h-16 animate-pulse rounded-xl bg-brand-line/30" />
          </div>
        </SectionCard>
      ) : error ? (
        <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 px-4 py-3 text-sm text-red-200">{error}</p>
      ) : !data ? null : (
        <>
      <KpiStrip items={kpiItems} title="Resumen del alumno" />

      <SectionCard title="Membresías" subtitle="Vigentes e históricas, con estado, saldo y estado de pago.">
        {memberships.length === 0 ? (
          <EmptyState title="Sin membresías" description="Este alumno todavía no tiene ningún plan asignado." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {memberships.map((membership) => (
              <MembershipCard key={membership.id} membership={membership} />
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Recurrencias vigentes" subtitle="Series activas que gobiernan las próximas reservas.">
        {recurringEnrollments.length === 0 ? (
          <EmptyState title="Sin recurrencias" description="Este alumno no tiene ninguna serie recurrente activa." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {recurringEnrollments.map((item) => (
              <RecurringCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Consumo" subtitle="Últimas clases descontadas de alguna membresía.">
        {consumption.items.length === 0 ? (
          <EmptyState title="Sin consumo" description="Este alumno todavía no ha consumido ninguna clase." />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {consumption.items.map((item) => (
                <ConsumptionCard key={item.id} item={item} />
              ))}
            </div>
            {consumption.has_more ? (
              <ShowMoreButton loading={loadingMoreKey === 'consumption_limit'} onClick={() => showMore('consumption_limit')} />
            ) : null}
          </>
        )}
      </SectionCard>

      <SectionCard title="Asistencia" subtitle="Últimos registros de asistencia, con quién los marcó.">
        {attendance.items.length === 0 ? (
          <EmptyState title="Sin asistencia" description="Este alumno todavía no tiene asistencia registrada." />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {attendance.items.map((item) => (
                <AttendanceCard key={item.id} item={item} />
              ))}
            </div>
            {attendance.has_more ? (
              <ShowMoreButton loading={loadingMoreKey === 'attendance_limit'} onClick={() => showMore('attendance_limit')} />
            ) : null}
          </>
        )}
      </SectionCard>

      <SectionCard title="Reservas" subtitle="Últimas inscripciones a clases, activas y canceladas.">
        {reservations.items.length === 0 ? (
          <EmptyState title="Sin reservas" description="Este alumno todavía no se ha inscrito a ninguna clase." />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {reservations.items.map((item) => (
                <ReservationCard key={item.id} item={item} />
              ))}
            </div>
            {reservations.has_more ? (
              <ShowMoreButton loading={loadingMoreKey === 'reservations_limit'} onClick={() => showMore('reservations_limit')} />
            ) : null}
          </>
        )}
      </SectionCard>
        </>
      )}
    </div>
  )
}
