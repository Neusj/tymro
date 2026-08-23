import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { classesApi, enrollmentsApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import BulkActionModal from '../components/BulkActionModal'
import ConfirmDialog from '../components/ConfirmDialog'
import ConfirmWithReasonDialog from '../components/ConfirmWithReasonDialog'
import DashboardHeader from '../components/DashboardHeader'
import DaySelector, { todayIsoDate } from '../components/DaySelector'
import FilterDropdown from '../components/FilterDropdown'
import FilterPanel from '../components/FilterPanel'
import KpiStrip from '../components/KpiStrip'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import ValueBadge from '../components/ui/ValueBadge'
import {
  applyTeacherClassFilters,
  calculateTeacherKpis,
  canOperateClass,
  extractFilterOptions,
  formatDateTime,
  sortClassesByStatusThenTime,
  ALL_STATUS_OPTIONS,
  HISTORY_STATUS_OPTIONS,
  UPCOMING_STATUS_OPTIONS,
  formatTimeRange,
} from './teacherClasses.helpers'

const initialFilters = {
  status: '',
  discipline: '',
}

const ATTENDANCE_STATUS_OPTIONS = [
  { value: 'present', label: 'Presente' },
  { value: 'absent', label: 'Ausente' },
  { value: 'late', label: 'Tarde' },
  { value: 'excused', label: 'Justificado' },
  { value: 'no_show', label: 'No asistio' },
]

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

function isVirtualClass(row) {
  return String(row?.id || '').startsWith('virtual:')
}

function BalanceBadge({ available, unlimited = false }) {
  const hasBalance = unlimited || Number(available || 0) > 0
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${hasBalance ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
      {unlimited ? 'Ilimitado' : hasBalance ? `${available} clases` : 'Sin saldo'}
    </span>
  )
}

// El roster ya manda el aviso resuelto (`plan_expiry_alert_level` + `_message`). Antes acá
// se traducía DOS veces: se sintetizaba un `validity_status` para pedirle el color al
// helper y después se descartaba su etiqueta, reescribiendo los textos a mano — con un
// `else` que mostraba "Sin plan" a cualquier estado no reconocido, incluido un alumno con
// plan vigente sin saldo.
function PlanStatusBadge({ student }) {
  return (
    <PlanAlertBadge
      level={student?.plan_expiry_alert_level}
      message={student?.plan_expiry_alert_message}
    />
  )
}

export default function TeacherClassesPage({ mode = 'upcoming' }) {
  const { user } = useAuth()
  const [classes, setClasses] = useState([])
  const [coverableClasses, setCoverableClasses] = useState([])
  const [selectedDate, setSelectedDate] = useState(todayIsoDate())
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [filters, setFilters] = useState(initialFilters)
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [claimingClass, setClaimingClass] = useState(null)
  const [releasingClass, setReleasingClass] = useState(null)
  const [detailClass, setDetailClass] = useState(null)
  const [classReasonAction, setClassReasonAction] = useState(null)
  const [suspendingClass, setSuspendingClass] = useState(null)
  const [reactivatingClass, setReactivatingClass] = useState(null)

  const [attendanceOpen, setAttendanceOpen] = useState(false)
  const [attendanceClass, setAttendanceClass] = useState(null)
  const [attendanceStudents, setAttendanceStudents] = useState([])
  const [attendanceMap, setAttendanceMap] = useState({})
  const [attendanceReadOnly, setAttendanceReadOnly] = useState(false)

  const [enrollOpen, setEnrollOpen] = useState(false)
  const [enrollClass, setEnrollClass] = useState(null)
  const [enrollStudents, setEnrollStudents] = useState([])
  const [enrollSelectedIds, setEnrollSelectedIds] = useState([])
  const [enrollSearch, setEnrollSearch] = useState('')
  const [enrolledOpen, setEnrolledOpen] = useState(false)
  const [enrolledClass, setEnrolledClass] = useState(null)
  const [enrolledStudents, setEnrolledStudents] = useState([])
  const [enrolledSelectedIds, setEnrolledSelectedIds] = useState([])
  const [enrolledSearch, setEnrolledSearch] = useState('')

  const listParams = useMemo(() => {
    const params = {
      ordering: mode === 'history' ? '-start_datetime' : 'start_datetime',
      teacher_scope: 'mine',
    }
    if (mode === 'history') {
      params.status_in = 'completed,completed_early'
    } else if (mode === 'upcoming') {
      params.status_in = 'scheduled,in_progress,suspended,cancelled'
    }
    return params
  }, [mode])

  const loadData = async () => {
    setLoading(true)
    try {
      if (mode === 'coverable') {
        const coverable = await classesApi.coverable(selectedDate, { ordering: 'start_datetime' })
        setClasses([])
        setCoverableClasses(coverable)
        return
      }
      const classesRequest =
        mode === 'all'
          ? classesApi.list(listParams)
          : classesApi.byDate(selectedDate, listParams)
      const list = await classesRequest
      setClasses(list)
      setCoverableClasses([])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las clases.'))
    } finally {
      setLoading(false)
    }
  }

  const claimSubstitution = async () => {
    if (!claimingClass) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await classesApi.claimSubstitution(claimingClass.id)
      setNotice(`${claimingClass.name || 'La clase'} fue tomada como suplencia y ahora aparece en Mis clases.`)
      setClaimingClass(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo tomar la suplencia.'))
    } finally {
      setWorking(false)
    }
  }

  const releaseSubstitution = async () => {
    if (!releasingClass) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await classesApi.releaseSubstitution(releasingClass.id)
      setNotice(`${releasingClass.name || 'La clase'} volvio a quedar disponible para cubrir.`)
      setReleasingClass(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo quitar la suplencia.'))
    } finally {
      setWorking(false)
    }
  }

  useEffect(() => {
    setError('')
    setNotice('')
    setFilters(initialFilters)
    setSelectedIds([])
    loadData()
  }, [mode, listParams, selectedDate])

  const sourceClasses = useMemo(
    () => (mode === 'coverable'
      ? coverableClasses.filter((row) => row.can_claim_substitution && !row.has_substitute)
      : classes),
    [classes, coverableClasses, mode],
  )
  const { disciplineOptions } = useMemo(() => extractFilterOptions(sourceClasses), [sourceClasses])
  const filteredClasses = useMemo(() => sortClassesByStatusThenTime(applyTeacherClassFilters(sourceClasses, filters), { descendingTime: mode === 'history' }), [sourceClasses, filters, mode])
  const kpis = useMemo(() => calculateTeacherKpis(filteredClasses, mode), [filteredClasses, mode])

  useEffect(() => {
    const filteredIds = new Set(filteredClasses.map((item) => item.id))
    setSelectedIds((prev) => prev.filter((id) => filteredIds.has(id)))
  }, [filteredClasses])

  const resetFilters = () => {
    setFilters(initialFilters)
  }

  const openAttendanceModal = async (row) => {
    setError('')
    setWorking(true)
    try {
      const students = await classesApi.enrolledStudents(row.id)
      const draft = {}
      students.forEach((item) => {
        draft[item.student_id] = item.attendance_status || 'absent'
      })
      setAttendanceStudents(students)
      setAttendanceMap(draft)
      setAttendanceClass(row)
      setAttendanceReadOnly(mode === 'history' || !canOperateClass(row))
      setAttendanceOpen(true)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la lista de asistencia.'))
    } finally {
      setWorking(false)
    }
  }

  const saveAttendance = async () => {
    if (!attendanceClass || attendanceReadOnly) {
      return
    }

    const payload = attendanceStudents.map((student) => ({
      student_id: student.student_id,
      status: attendanceMap[student.student_id] || 'absent',
    }))

    setWorking(true)
    setError('')
    try {
      await classesApi.saveAttendance(attendanceClass.id, payload)
      setAttendanceOpen(false)
      setAttendanceClass(null)
      setAttendanceStudents([])
      setAttendanceMap({})
      setAttendanceReadOnly(false)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo guardar la asistencia.'))
    } finally {
      setWorking(false)
    }
  }

  const openEnrollModal = async (row) => {
    if (!canOperateClass(row)) {
      setError('No puedes inscribir alumnos en una clase cerrada o cancelada.')
      return
    }

    setError('')
    setWorking(true)
    try {
      const [candidates, enrolled] = await Promise.all([classesApi.enrollableStudents(row.id), classesApi.enrolledStudents(row.id)])
      setEnrollClass(row)
      setEnrollStudents(candidates)
      setEnrolledClass(row)
      setEnrolledStudents(enrolled)
      setEnrollSelectedIds([])
      setEnrollSearch('')
      setEnrollOpen(true)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la lista de alumnos para inscripcion.'))
    } finally {
      setWorking(false)
    }
  }

  const openEnrolledModal = async (row) => {
    if (!canOperateClass(row)) {
      setError('No puedes modificar inscripciones en una clase cerrada o cancelada.')
      return
    }

    setError('')
    setWorking(true)
    try {
      const [candidates, enrolled] = await Promise.all([classesApi.enrollableStudents(row.id), classesApi.enrolledStudents(row.id)])
      setEnrollClass(row)
      setEnrollStudents(candidates)
      setEnrolledClass(row)
      setEnrolledStudents(enrolled)
      setEnrolledSelectedIds([])
      setEnrolledSearch('')
      setEnrolledOpen(true)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la lista de alumnos inscritos.'))
    } finally {
      setWorking(false)
    }
  }

  const syncEnrollmentPools = async (classId) => {
    if (!classId) {
      return
    }
    const [candidates, enrolled] = await Promise.all([classesApi.enrollableStudents(classId), classesApi.enrolledStudents(classId)])
    setEnrollStudents(candidates)
    setEnrolledStudents(enrolled)
  }

  const submitEnrollments = async () => {
    if (!enrollClass || enrollSelectedIds.length === 0) {
      return
    }

    const selectedStudents = enrollStudents.filter((student) => enrollSelectedIds.includes(student.id))
    const withoutBalance = selectedStudents.filter((student) => !student.has_available_classes)
    if (withoutBalance.length > 0) {
      setError('Alumno sin clases disponibles')
      return
    }

    setWorking(true)
    setError('')
    try {
      for (const studentId of enrollSelectedIds) {
        // eslint-disable-next-line no-await-in-loop
        await enrollmentsApi.create({
          gym_class: enrollClass.id,
          student: studentId,
          status: 'active',
        })
      }
      setEnrollSelectedIds([])
      setEnrollSearch('')
      await syncEnrollmentPools(enrollClass.id)
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      if (detail?.student?.[0]) {
        setError(detail.student[0])
      } else if (detail?.gym_class?.[0]) {
        setError(detail.gym_class[0])
      } else {
        setError(firstApiError(detail, 'No se pudo completar la inscripcion de alumnos.'))
      }
    } finally {
      setWorking(false)
    }
  }

  const removeSelectedEnrollments = async () => {
    if (!enrolledClass || enrolledSelectedIds.length === 0) {
      return
    }

    setWorking(true)
    setError('')
    try {
      for (const enrollmentId of enrolledSelectedIds) {
        // eslint-disable-next-line no-await-in-loop
        await enrollmentsApi.cancel(enrollmentId)
      }
      setEnrolledSelectedIds([])
      setEnrolledSearch('')
      await syncEnrollmentPools(enrolledClass.id)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron quitar los alumnos seleccionados.'))
    } finally {
      setWorking(false)
    }
  }

  const closeClass = async (comment) => {
    if (!classReasonAction?.row || !comment?.trim()) {
      return
    }

    const { row, actionName } = classReasonAction
    setWorking(true)
    setError('')
    try {
      if (actionName === 'cancel') {
        await classesApi.cancel(row.id, comment.trim())
      } else {
        await classesApi.completeEarly(row.id, comment.trim())
      }
      setClassReasonAction(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo actualizar la clase.'))
    } finally {
      setWorking(false)
    }
  }

  // Suspende la clase (pausa reactivable): cambia el estado a 'suspended' y avisa
  // por email a los alumnos inscritos. NO es lo mismo que el cierre anticipado.
  const suspendClass = async (reason) => {
    if (!suspendingClass?.id) {
      return
    }

    setWorking(true)
    setError('')
    try {
      await classesApi.suspend(suspendingClass.id, { suspend_reason: reason.trim() })
      setSuspendingClass(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo suspender la clase.'))
    } finally {
      setWorking(false)
    }
  }

  // Reactiva una clase suspendida o cancelada (vuelve a 'scheduled'/'in_progress' segun la hora).
  const reactivateClass = async () => {
    if (!reactivatingClass?.id) {
      return
    }

    setWorking(true)
    setError('')
    try {
      await classesApi.reactivate(reactivatingClass.id)
      setReactivatingClass(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo reactivar la clase.'))
    } finally {
      setWorking(false)
    }
  }

  const runBulkAction = async ({ action, comment }) => {
    setError('')
    if (selectedIds.length === 0) {
      setError('Selecciona al menos una clase del conjunto filtrado.')
      return
    }
    const persistedIds = selectedIds.filter((id) => !String(id).startsWith('virtual:'))
    if (persistedIds.length === 0) {
      setError('Las clases proyectadas se podran operar cuando exista la instancia.')
      return
    }

    setWorking(true)
    try {
      await classesApi.bulkClose({
        class_ids: persistedIds,
        action,
        comment,
      })
      setSelectedIds([])
      setBulkModalOpen(false)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo ejecutar la accion masiva.'))
    } finally {
      setWorking(false)
    }
  }

  const classColumns = useMemo(() => {
    const base = [
      { key: 'name', label: 'Clase' },
      { key: 'branch_name', label: 'Sucursal' },
      { key: 'class_type_name', label: 'Tipo', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      { key: 'class_template_name', label: 'Serie', render: (row) => row.class_template_name || '-' },
      {
        key: 'teacher_assignment',
        label: 'Rol',
        mobile: 'meta',
        render: (row) =>
          row.has_substitute && String(row.substitute_teacher || '') === String(user?.id || '') ? (
            <span className="inline-flex rounded-full border border-brand-orange/50 bg-brand-orange/10 px-2 py-0.5 text-[11px] font-semibold text-brand-orange">
              Suplencia
            </span>
          ) : (
            <span className="inline-flex rounded-full border border-brand-line px-2 py-0.5 text-[11px] font-semibold text-brand-muted">
              Titular
            </span>
          ),
      },
      {
        key: 'start_datetime',
        label: 'Inicio',
        mobile: 'secondary',
        mobileLabel: 'Hora',
        mobilePriority: 1,
        render: (row) => formatDateTime(row.start_datetime),
        mobileRender: (row) => formatTimeRange(row.start_datetime, row.end_datetime),
      },
      { key: 'end_datetime', label: 'Termino', render: (row) => formatDateTime(row.end_datetime) },
      { key: 'status', label: 'Estado', render: (row) => <ValueBadge kind="class_status" value={row.status} /> },
      {
        key: 'capacity',
        label: mode === 'history' ? 'Asistencia / Cupos' : 'Inscritos / Cupos',
        sortAccessor: (row) => row.capacity,
        render: (row) => {
          const people = mode === 'history' ? row.present_attendances_count ?? row.attendances_count ?? 0 : row.enrollments_count || 0
          return `${people}/${row.capacity}`
        },
      },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        hideActionsInDetail: true,
        mobilePrimaryReplacesDetail: true,
        mobilePrimary: (row) =>
          isVirtualClass(row) ? (
            <button
              type="button"
              disabled
              className="rounded-lg border border-brand-line px-3 py-2 text-center text-xs font-semibold text-brand-white opacity-60"
            >
              Asistencia
            </button>
          ) : (
            <Link
              to={`/teacher/classes/${row.id}/attendance`}
              className="block rounded-lg border border-brand-blue/70 bg-brand-blue/15 px-3 py-2 text-center text-xs font-semibold text-brand-white transition hover:border-brand-blue"
            >
              Asistencia
            </Link>
          ),
        mobileActionsRender: (row) => {
          const canOperate = canOperateClass(row)
          const isSuspended = row.status === 'suspended'
          const isCancelled = row.status === 'cancelled'
          const isVirtual = isVirtualClass(row)
          return (
            <>
              {mode === 'upcoming' && isSuspended ? (
                <>
                  <button
                    type="button"
                    disabled={working || isVirtual}
                    onClick={() => setReactivatingClass(row)}
                    className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                  >
                    Reactivar clase
                  </button>
                  <button
                    type="button"
                    disabled={working || isVirtual}
                    onClick={() => setClassReasonAction({ row, actionName: 'cancel' })}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar clase
                  </button>
                </>
              ) : null}
              {mode === 'upcoming' && isCancelled ? (
                <button
                  type="button"
                  disabled={working || isVirtual}
                  onClick={() => setReactivatingClass(row)}
                  className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                >
                  Reabrir clase
                </button>
              ) : null}
              {mode === 'upcoming' && !isSuspended && !isCancelled ? (
                <>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => openEnrollModal(row)}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Inscribir alumnos
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => openEnrolledModal(row)}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Ver inscritos
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => setSuspendingClass(row)}
                    className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
                  >
                    Suspender clase
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => setClassReasonAction({ row, actionName: 'complete_early' })}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Finalizar (cierre anticipado)
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => setClassReasonAction({ row, actionName: 'cancel' })}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar clase
                  </button>
                </>
              ) : null}
            </>
          )
        },
        render: (row) => {
          const canOperate = canOperateClass(row)
          const isSuspended = row.status === 'suspended'
          const isCancelled = row.status === 'cancelled'
          const isVirtual = isVirtualClass(row)
          return (
            <>
              {isVirtual ? (
                <button
                  type="button"
                  disabled
                  className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white opacity-60"
                >
                  {mode === 'history' ? 'Ver asistencia' : 'Tomar asistencia'}
                </button>
              ) : (
                <Link
                  to={`/teacher/classes/${row.id}/attendance`}
                  className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
                >
                  {mode === 'history' ? 'Ver asistencia' : 'Tomar asistencia'}
                </Link>
              )}
              {mode === 'upcoming' && isSuspended ? (
                <>
                  <button
                    type="button"
                    disabled={working || isVirtual}
                    onClick={() => setReactivatingClass(row)}
                    className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                  >
                    Reactivar clase
                  </button>
                  <button
                    type="button"
                    disabled={working || isVirtual}
                    onClick={() => setClassReasonAction({ row, actionName: 'cancel' })}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar clase
                  </button>
                </>
              ) : null}
              {mode === 'upcoming' && isCancelled ? (
                <button
                  type="button"
                  disabled={working || isVirtual}
                  onClick={() => setReactivatingClass(row)}
                  className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                >
                  Reabrir clase
                </button>
              ) : null}
              {mode === 'upcoming' && !isSuspended && !isCancelled ? (
                <>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => openEnrollModal(row)}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Inscribir alumnos
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => openEnrolledModal(row)}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Ver inscritos
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => setSuspendingClass(row)}
                    className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
                  >
                    Suspender clase
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => setClassReasonAction({ row, actionName: 'complete_early' })}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Finalizar (cierre anticipado)
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => setClassReasonAction({ row, actionName: 'cancel' })}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar clase
                  </button>
                </>
              ) : null}
            </>
          )
        },
      },
    ]

    return base
  }, [mode, working, user?.id])

  const coverableColumns = useMemo(
    () => [
      { key: 'name', label: 'Clase' },
      { key: 'teacher_name', label: 'Titular' },
      { key: 'branch_name', label: 'Sucursal' },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      {
        key: 'start_datetime',
        label: 'Inicio',
        mobile: 'secondary',
        mobileLabel: 'Hora',
        mobilePriority: 1,
        render: (row) => formatDateTime(row.start_datetime),
        mobileRender: (row) => formatTimeRange(row.start_datetime, row.end_datetime),
      },
      { key: 'end_datetime', label: 'Termino', render: (row) => formatDateTime(row.end_datetime) },
      { key: 'status', label: 'Estado', render: (row) => <ValueBadge kind="class_status" value={row.status} /> },
      {
        key: 'substitute_display_name',
        label: 'Suplente',
        mobile: 'hidden',
        render: (row) => (row.has_substitute ? row.substitute_display_name || '-' : <span className="text-brand-muted">Disponible</span>),
      },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        mobilePrimary: (row) =>
          row.can_claim_substitution ? (
            <button
              type="button"
              disabled={working}
              onClick={() => setClaimingClass(row)}
              className="rounded-lg border border-brand-orange bg-brand-orange px-3 py-2 text-center text-xs font-semibold text-white transition hover:border-brand-orange/80 hover:bg-brand-orange/90 disabled:opacity-60"
            >
              Cubrir esta clase
            </button>
          ) : null,
        render: (row) => {
          const canReleaseSubstitution =
            row.can_release_substitution ||
            (
              row.has_substitute &&
              String(row.substitute_teacher || '') === String(user?.id || '') &&
              ['scheduled', 'in_progress'].includes(row.status)
            )
          if (row.can_claim_substitution) {
            return (
              <>
                <button
                  type="button"
                  disabled={working}
                  onClick={() => setClaimingClass(row)}
                  className="w-full rounded-lg border border-brand-orange bg-brand-orange px-2.5 py-2 text-left text-xs font-semibold text-white transition hover:border-brand-orange/80 hover:bg-brand-orange/90 disabled:opacity-60"
                >
                  Cubrir esta clase
                </button>
                <button
                  type="button"
                  onClick={() => setDetailClass(row)}
                  className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
                >
                  Ver detalles
                </button>
              </>
            )
          }
          if (canReleaseSubstitution) {
            return (
              <button
                type="button"
                disabled={working}
                onClick={() => setReleasingClass(row)}
                className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-red hover:text-red-100 disabled:opacity-60"
              >
                Quitar suplencia
              </button>
            )
          }
          return <span className="text-xs text-brand-muted">Suplencia tomada</span>
        },
      },
    ],
    [user?.id, working],
  )

  const title =
    mode === 'coverable'
      ? 'Teacher · Clases por cubrir'
      : mode === 'all'
        ? 'Teacher · Mis clases'
        : mode === 'history'
          ? 'Teacher · Clases realizadas'
          : 'Teacher · Mis clases'
  const subtitle =
    mode === 'coverable'
      ? 'Clases disponibles para tomar como suplente en el dia seleccionado.'
      : mode === 'all'
        ? 'Vista completa de tus clases con filtros, asistencia, inscripciones y acciones operativas.'
        : mode === 'history'
          ? 'Historico de clases para revisar asistentes y resultados finales.'
          : 'Clases asignadas a ti y clases que aceptaste cubrir como suplente.'

  const filteredEnrollStudents = enrollStudents.filter((student) => {
    const query = enrollSearch.trim().toLowerCase()
    if (!query) {
      return true
    }
    const text = `${student.name || ''} ${student.username || ''} ${student.email || ''}`.toLowerCase()
    return text.includes(query)
  })
  const filteredEnrolledStudents = enrolledStudents.filter((student) => {
    const query = enrolledSearch.trim().toLowerCase()
    if (!query) {
      return true
    }
    const text = `${student.name || ''} ${student.username || ''} ${student.email || ''}`.toLowerCase()
    return text.includes(query)
  })

  const statusOptions = mode === 'all' ? ALL_STATUS_OPTIONS : mode === 'history' ? HISTORY_STATUS_OPTIONS : UPCOMING_STATUS_OPTIONS
  const activeColumns = mode === 'coverable' ? coverableColumns : classColumns

  return (
    <div className="space-y-6">
      <DashboardHeader title={title} subtitle={subtitle} />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}

      {mode === 'all' ? null : <DaySelector value={selectedDate} onChange={setSelectedDate} />}

      <section className="card-surface space-y-4 p-5">
        <KpiStrip
          items={[
            { label: 'Total clases', value: kpis.totalClasses },
            { label: kpis.peopleLabel, value: kpis.totalPeople },
            { label: 'Ocupacion promedio', value: `${kpis.occupancy}%` },
          ]}
        />

        <FilterPanel
          activeCount={(filters.status ? 1 : 0) + (filters.discipline ? 1 : 0)}
          onClear={resetFilters}
        >
          <div className="flex flex-wrap items-end gap-2">
            <FilterDropdown
              label="Estado"
              value={filters.status}
              options={statusOptions}
              onChange={(value) => setFilters((prev) => ({ ...prev, status: value }))}
            />
            <FilterDropdown
              label="Disciplina"
              value={filters.discipline}
              options={disciplineOptions}
              onChange={(value) => setFilters((prev) => ({ ...prev, discipline: value }))}
            />
          </div>
        </FilterPanel>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="panel-title">
            {mode === 'all'
              ? 'Detalle de clases (filtrado)'
              : mode === 'coverable'
                ? 'Clases por cubrir (filtrado)'
              : mode === 'history'
                ? 'Detalle de clases realizadas (filtrado)'
                : 'Detalle de mis clases (filtrado)'}
          </h2>
          {mode === 'upcoming' ? (
            <button
              type="button"
              disabled={!selectedIds.length}
              onClick={() => setBulkModalOpen(true)}
              className="btn-ghost text-xs"
            >
              Finalizar/Cancelar ({selectedIds.length})
            </button>
          ) : null}
        </div>

        <DataTable
          columns={activeColumns}
          data={filteredClasses}
          loading={loading}
          selectableRows={mode !== 'coverable'}
          selectAllScope="filtered"
          selectedRowIds={selectedIds}
          onSelectedRowIdsChange={setSelectedIds}
          disablePagination={mode !== 'all'}
        />
      </section>

      <BulkActionModal
        open={mode === 'upcoming' && bulkModalOpen}
        title="Finalizar o cancelar clases"
        selectedCount={selectedIds.length}
        loading={working}
        actions={[
          {
            value: 'complete_early',
            label: 'Finalizar anticipadamente',
            description: 'Cierra anticipadamente las clases seleccionadas (estado finalizada anticipada).',
          },
          {
            value: 'cancel',
            label: 'Cancelar clases',
            description: 'Cancela clases seleccionadas y preserva historico operativo.',
          },
        ]}
        requiresCommentActions={['complete_early', 'cancel']}
        defaultAction="cancel"
        onClose={() => setBulkModalOpen(false)}
        onConfirm={runBulkAction}
      />

      <ConfirmDialog
        open={Boolean(claimingClass)}
        title="Cubrir esta clase"
        description={`Tomaras ${claimingClass?.name || 'esta clase'} como suplente. El profesor titular se mantiene.`}
        confirmLabel="Cubrir clase"
        loading={working}
        onCancel={() => setClaimingClass(null)}
        onConfirm={claimSubstitution}
      />

      <ConfirmDialog
        open={Boolean(releasingClass)}
        title="Quitar suplencia"
        description={`Dejaras de cubrir ${releasingClass?.name || 'esta clase'} y volvera a quedar disponible para otros profesores.`}
        confirmLabel="Quitar suplencia"
        loading={working}
        onCancel={() => setReleasingClass(null)}
        onConfirm={releaseSubstitution}
      />

      <FormModal
        open={Boolean(detailClass)}
        title={detailClass ? `Detalles · ${detailClass.name}` : 'Detalles'}
        onClose={() => setDetailClass(null)}
      >
        <div className="divide-y divide-brand-line text-sm">
          {[
            ['Profesor titular', detailClass?.teacher_name],
            ['Sucursal', detailClass?.branch_name],
            ['Disciplina', detailClass?.discipline_name],
            ['Tipo', detailClass?.class_type_name],
            ['Inicio', formatDateTime(detailClass?.start_datetime)],
            ['Termino', formatDateTime(detailClass?.end_datetime)],
            ['Estado', detailClass?.status],
            ['Cupos', detailClass ? `${detailClass.enrollments_count || 0}/${detailClass.capacity}` : '-'],
          ].map(([label, value]) => (
            <div key={label} className="flex items-start justify-between gap-4 py-2.5">
              <p className="shrink-0 text-xs font-semibold uppercase tracking-wide text-brand-dim">{label}</p>
              <p className="min-w-0 text-right text-brand-white">{value || '-'}</p>
            </div>
          ))}
        </div>
      </FormModal>

      <ConfirmWithReasonDialog
        open={Boolean(classReasonAction)}
        title={classReasonAction?.actionName === 'cancel' ? 'Cancelar clase' : 'Finalizar anticipadamente'}
        description={`Se actualizara ${classReasonAction?.row?.name || 'esta clase'} preservando trazabilidad.`}
        reasonLabel={classReasonAction?.actionName === 'cancel' ? 'Motivo de cancelacion' : 'Motivo de cierre anticipado'}
        confirmLabel={classReasonAction?.actionName === 'cancel' ? 'Cancelar clase' : 'Finalizar clase'}
        variant={classReasonAction?.actionName === 'cancel' ? 'danger' : 'warning'}
        loading={working}
        onCancel={() => {
          if (!working) {
            setClassReasonAction(null)
          }
        }}
        onConfirm={closeClass}
      />

      <ConfirmWithReasonDialog
        open={Boolean(suspendingClass)}
        title="Suspender clase"
        description={`Se pausara ${suspendingClass?.name || 'esta clase'} y podra reactivarse despues.`}
        reasonLabel="Motivo de suspension (opcional)"
        reasonRequired={false}
        confirmLabel="Suspender clase"
        variant="warning"
        loading={working}
        onCancel={() => {
          if (!working) {
            setSuspendingClass(null)
          }
        }}
        onConfirm={suspendClass}
      />

      <ConfirmDialog
        open={Boolean(reactivatingClass)}
        title={reactivatingClass?.status === 'cancelled' ? 'Reabrir clase' : 'Reactivar clase'}
        description={
          reactivatingClass?.status === 'cancelled'
            ? `Se reabrira ${reactivatingClass?.name || 'esta clase'}. Las reservas canceladas no se restauraran automaticamente; los alumnos deberan volver a inscribirse o reservar si tienen cupos disponibles.`
            : `Se reactivara ${reactivatingClass?.name || 'esta clase suspendida'}.`
        }
        confirmLabel={reactivatingClass?.status === 'cancelled' ? 'Reabrir clase' : 'Reactivar clase'}
        variant="default"
        loading={working}
        onCancel={() => {
          if (!working) {
            setReactivatingClass(null)
          }
        }}
        onConfirm={reactivateClass}
      />

      <FormModal
        open={attendanceOpen}
        closeDisabled={working}
        onClose={() => {
          setAttendanceOpen(false)
          setAttendanceClass(null)
          setAttendanceStudents([])
          setAttendanceMap({})
          setAttendanceReadOnly(false)
        }}
        title={attendanceClass ? `Asistencia · ${attendanceClass.name}` : 'Asistencia'}
      >
        <div className="space-y-3">
          {attendanceStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay alumnos inscritos activos en esta clase.</p> : null}

          <div className="max-h-[24rem] space-y-2 overflow-y-auto rounded-lg border border-brand-line p-2">
            {attendanceStudents.map((student) => (
              <label key={student.student_id} className="flex items-center justify-between gap-3 rounded-lg border border-brand-line px-3 py-2 text-sm">
                <span>
                  <span className="font-semibold">{student.name}</span>
                  <span className="block text-xs text-brand-muted">{student.email || student.username}</span>
                  <span className="mt-1 block">
                    <BalanceBadge available={student.available_classes} unlimited={student.unlimited_classes} />
                  </span>
                  <span className="mt-1 block">
                    <PlanStatusBadge student={student} />
                  </span>
                </span>
                <span className="flex flex-col items-end gap-2 text-xs text-brand-muted">
                  <ValueBadge kind="attendance_status" value={attendanceMap[student.student_id]} />
                  <span className="grid grid-cols-2 gap-1 sm:grid-cols-5">
                    {ATTENDANCE_STATUS_OPTIONS.map((option) => {
                      const selected = attendanceMap[student.student_id] === option.value
                      return (
                        <button
                          key={option.value}
                          type="button"
                          disabled={attendanceReadOnly}
                          onClick={() =>
                            setAttendanceMap((prev) => ({
                              ...prev,
                              [student.student_id]: option.value,
                            }))
                          }
                          className={`rounded-lg border px-2 py-1 text-[11px] transition disabled:opacity-60 ${
                            selected ? 'border-brand-blue bg-brand-blue/20 text-brand-white' : 'border-brand-line text-brand-muted hover:text-brand-white'
                          }`}
                        >
                          {option.label}
                        </button>
                      )
                    })}
                  </span>
                </span>
              </label>
            ))}
          </div>

          {!attendanceReadOnly ? (
            <div className="flex justify-end">
              <button
                type="button"
                disabled={working || attendanceStudents.length === 0}
                onClick={saveAttendance}
                className="btn-primary"
              >
                {working ? 'Guardando...' : 'Guardar asistencia'}
              </button>
            </div>
          ) : (
            <p className="text-xs text-brand-muted">Vista de solo lectura para clases realizadas o cerradas.</p>
          )}
        </div>
      </FormModal>

      <FormModal
        open={enrollOpen}
        closeDisabled={working}
        onClose={() => {
          setEnrollOpen(false)
          setEnrollClass(null)
          setEnrollStudents([])
          setEnrollSelectedIds([])
          setEnrollSearch('')
        }}
        title={enrollClass ? `Inscribir alumnos · ${enrollClass.name}` : 'Inscribir alumnos'}
      >
        <div className="space-y-3">
          <label className="space-y-1 text-sm">
            <span>Buscar alumno</span>
            <input
              value={enrollSearch}
              onChange={(event) => setEnrollSearch(event.target.value)}
              placeholder="Nombre, username o email"
              className="field"
            />
          </label>

          <div className="max-h-[24rem] space-y-2 overflow-y-auto rounded-lg border border-brand-line p-2">
            {filteredEnrollStudents.map((student) => (
              <label key={student.id} className="flex items-center justify-between gap-3 rounded-lg border border-brand-line px-3 py-2 text-sm">
                <span>
                  <span className="font-semibold">{student.name}</span>
                  <span className="block text-xs text-brand-muted">{student.email || student.username}</span>
                  <span className="mt-1 block">
                    <BalanceBadge available={student.available_classes} unlimited={student.unlimited_classes} />
                  </span>
                  <span className="mt-1 block">
                    <PlanStatusBadge student={student} />
                  </span>
                </span>
                <input
                  type="checkbox"
                  disabled={!student.has_available_classes}
                  checked={enrollSelectedIds.includes(student.id)}
                  onChange={(event) =>
                    setEnrollSelectedIds((prev) =>
                      event.target.checked ? [...prev, student.id] : prev.filter((id) => id !== student.id),
                    )
                  }
                />
              </label>
            ))}
            {enrollStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay alumnos disponibles para inscribir.</p> : null}
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              disabled={working || enrollSelectedIds.length === 0}
              onClick={submitEnrollments}
              className="btn-primary"
            >
              {working ? 'Inscribiendo...' : 'Inscribir seleccionados'}
            </button>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={working || !enrollClass}
              onClick={() => {
                setEnrollOpen(false)
                setEnrolledOpen(true)
                setEnrolledClass(enrollClass)
                setEnrolledSelectedIds([])
                setEnrolledSearch('')
              }}
              className="btn-ghost"
            >
              Ver inscritos
            </button>
          </div>
        </div>
      </FormModal>

      <FormModal
        open={enrolledOpen}
        closeDisabled={working}
        onClose={() => {
          setEnrolledOpen(false)
          setEnrolledClass(null)
          setEnrolledStudents([])
          setEnrolledSelectedIds([])
          setEnrolledSearch('')
        }}
        title={enrolledClass ? `Ver inscritos · ${enrolledClass.name}` : 'Ver inscritos'}
      >
        <div className="space-y-3">
          <label className="space-y-1 text-sm">
            <span>Buscar inscrito</span>
            <input
              value={enrolledSearch}
              onChange={(event) => setEnrolledSearch(event.target.value)}
              placeholder="Nombre, username o email"
              className="field"
            />
          </label>

          <div className="max-h-[24rem] space-y-2 overflow-y-auto rounded-lg border border-brand-line p-2">
            {filteredEnrolledStudents.map((student) => (
              <label key={student.enrollment_id} className="flex items-center justify-between gap-3 rounded-lg border border-brand-line px-3 py-2 text-sm">
                <span>
                  <span className="font-semibold">{student.name}</span>
                  <span className="block text-xs text-brand-muted">{student.email || student.username}</span>
                  <span className="mt-1 block">
                    <BalanceBadge available={student.available_classes} unlimited={student.unlimited_classes} />
                  </span>
                </span>
                <input
                  type="checkbox"
                  checked={enrolledSelectedIds.includes(student.enrollment_id)}
                  onChange={(event) =>
                    setEnrolledSelectedIds((prev) =>
                      event.target.checked ? [...prev, student.enrollment_id] : prev.filter((id) => id !== student.enrollment_id),
                    )
                  }
                />
              </label>
            ))}
            {enrolledStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay alumnos inscritos en esta clase.</p> : null}
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={working || !enrolledClass}
              onClick={() => {
                setEnrolledOpen(false)
                setEnrollOpen(true)
                setEnrollClass(enrolledClass)
                setEnrollSelectedIds([])
                setEnrollSearch('')
              }}
              className="btn-ghost"
            >
              Inscribir alumnos
            </button>
            <button
              type="button"
              disabled={working || enrolledSelectedIds.length === 0}
              onClick={removeSelectedEnrollments}
              className="btn-danger"
            >
              {working ? 'Quitando...' : 'Quitar seleccionados'}
            </button>
          </div>
        </div>
      </FormModal>
    </div>
  )
}
