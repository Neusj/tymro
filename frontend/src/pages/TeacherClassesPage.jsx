import { useEffect, useMemo, useState } from 'react'
import { classesApi, enrollmentsApi } from '../api/client'
import BulkActionModal from '../components/BulkActionModal'
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
  HISTORY_STATUS_OPTIONS,
  UPCOMING_STATUS_OPTIONS,
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
  const [classes, setClasses] = useState([])
  const [selectedDate, setSelectedDate] = useState(todayIsoDate())
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  const [filters, setFilters] = useState(initialFilters)
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkModalOpen, setBulkModalOpen] = useState(false)

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
    }
    if (mode === 'history') {
      params.status_in = 'completed,completed_early'
    } else {
      params.status_in = 'scheduled,in_progress,suspended'
    }
    return params
  }, [mode])

  const loadData = async () => {
    setLoading(true)
    try {
      const list = await classesApi.byDate(selectedDate, listParams)
      setClasses(list)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las clases.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setError('')
    setFilters(initialFilters)
    setSelectedIds([])
    loadData()
  }, [mode, listParams, selectedDate])

  const { disciplineOptions } = useMemo(() => extractFilterOptions(classes), [classes])
  const filteredClasses = useMemo(() => applyTeacherClassFilters(classes, filters), [classes, filters])
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
      window.alert('Alumno sin clases disponibles')
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

  const closeClass = async (row, actionName) => {
    const comment = window.prompt(actionName === 'cancel' ? 'Motivo de cancelacion' : 'Motivo de cierre anticipado')
    if (!comment || !comment.trim()) {
      return
    }

    setWorking(true)
    setError('')
    try {
      if (actionName === 'cancel') {
        await classesApi.cancel(row.id, comment.trim())
      } else {
        await classesApi.completeEarly(row.id, comment.trim())
      }
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo actualizar la clase.'))
    } finally {
      setWorking(false)
    }
  }

  // Suspende la clase (pausa reactivable): cambia el estado a 'suspended' y avisa
  // por email a los alumnos inscritos. NO es lo mismo que el cierre anticipado.
  const suspendClass = async (row) => {
    const reason = window.prompt('Motivo de suspension (opcional)')
    if (reason === null) {
      return // el usuario canceló el prompt
    }

    setWorking(true)
    setError('')
    try {
      await classesApi.suspend(row.id, { suspend_reason: reason.trim() })
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo suspender la clase.'))
    } finally {
      setWorking(false)
    }
  }

  // Reactiva una clase suspendida (vuelve a 'scheduled'/'in_progress' según la hora).
  const reactivateClass = async (row) => {
    if (!window.confirm('Reactivar esta clase suspendida?')) {
      return
    }

    setWorking(true)
    setError('')
    try {
      await classesApi.reactivate(row.id)
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
      { key: 'start_datetime', label: 'Inicio', render: (row) => formatDateTime(row.start_datetime) },
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
        render: (row) => {
          const canOperate = canOperateClass(row)
          const isSuspended = row.status === 'suspended'
          const isVirtual = isVirtualClass(row)
          return (
            <>
              <button
                type="button"
                disabled={working || isVirtual}
                onClick={() => openAttendanceModal(row)}
                className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
              >
                {mode === 'history' ? 'Ver asistencia' : 'Tomar asistencia'}
              </button>
              {mode === 'upcoming' && isSuspended ? (
                <>
                  <button
                    type="button"
                    disabled={working || isVirtual}
                    onClick={() => reactivateClass(row)}
                    className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                  >
                    Reactivar clase
                  </button>
                  <button
                    type="button"
                    disabled={working || isVirtual}
                    onClick={() => closeClass(row, 'cancel')}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar clase
                  </button>
                </>
              ) : null}
              {mode === 'upcoming' && !isSuspended ? (
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
                    onClick={() => suspendClass(row)}
                    className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
                  >
                    Suspender clase
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => closeClass(row, 'complete_early')}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Finalizar (cierre anticipado)
                  </button>
                  <button
                    type="button"
                    disabled={!canOperate || working || isVirtual}
                    onClick={() => closeClass(row, 'cancel')}
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
  }, [mode, working])

  const title = mode === 'history' ? 'Teacher · Clases realizadas' : 'Teacher · Proximas clases'
  const subtitle =
    mode === 'history'
      ? 'Historico de clases para revisar asistentes y resultados finales.'
      : 'Operacion diaria de tus clases: inscritos, ocupacion y acciones de suspension/cancelacion.'

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

  const statusOptions = mode === 'history' ? HISTORY_STATUS_OPTIONS : UPCOMING_STATUS_OPTIONS

  return (
    <div className="space-y-6">
      <DashboardHeader title={title} subtitle={subtitle} />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <DaySelector value={selectedDate} onChange={setSelectedDate} />

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

      <section className="card-surface p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="panel-title">{mode === 'history' ? 'Detalle de clases realizadas (filtrado)' : 'Detalle de proximas clases (filtrado)'}</h2>
          {mode === 'upcoming' ? (
            <button
              type="button"
              disabled={!selectedIds.length}
              onClick={() => setBulkModalOpen(true)}
              className="rounded-lg border border-brand-orange px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-50"
            >
              Finalizar/Cancelar ({selectedIds.length})
            </button>
          ) : null}
        </div>

        <DataTable
          columns={classColumns}
          data={filteredClasses}
          loading={loading}
          selectableRows
          selectAllScope="filtered"
          selectedRowIds={selectedIds}
          onSelectedRowIdsChange={setSelectedIds}
          defaultSort={{ key: 'start_datetime', direction: mode === 'history' ? 'desc' : 'asc' }}
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

      <FormModal
        open={attendanceOpen}
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
                className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
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
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
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
              className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
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
              className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white disabled:opacity-60"
            >
              Ver inscritos
            </button>
          </div>
        </div>
      </FormModal>

      <FormModal
        open={enrolledOpen}
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
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
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
              className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white disabled:opacity-60"
            >
              Inscribir alumnos
            </button>
            <button
              type="button"
              disabled={working || enrolledSelectedIds.length === 0}
              onClick={removeSelectedEnrollments}
              className="rounded-xl bg-brand-red px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {working ? 'Quitando...' : 'Quitar seleccionados'}
            </button>
          </div>
        </div>
      </FormModal>
    </div>
  )
}
