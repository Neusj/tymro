import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { classesApi, enrollmentsApi, usersApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { canManageOperational } from '../utils/roles'
import { firstApiError } from '../utils/format'

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

// Solo 2 estados marcables por el admin (igual que el toggle del profe en
// TeacherClassesPage); el historial de correcciones sí puede MOSTRAR cualquier
// status heredado (p.ej. 'late'/'excused'/'no_show' marcados antes por el profe).
const ATTENDANCE_TOGGLE_OPTIONS = [
  { value: 'present', label: 'Presente' },
  { value: 'absent', label: 'Ausente' },
]

export default function GymAdminClassDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const canManage = canManageOperational(user?.role)
  const [gymClass, setGymClass] = useState(null)
  const [students, setStudents] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedStudentId, setSelectedStudentId] = useState('')
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(null)

  const [attendanceMap, setAttendanceMap] = useState({})
  const [attendanceSaving, setAttendanceSaving] = useState(false)
  const [attendanceError, setAttendanceError] = useState('')

  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')

  const loadData = async () => {
    setLoading(true)
    try {
      const [classData, studentsData] = await Promise.all([classesApi.retrieve(id), usersApi.list({ role: 'student' })])
      setGymClass(classData)
      setStudents(studentsData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  const enrollments = gymClass?.enrollments || []
  const activeEnrollments = enrollments.filter((item) => item.status === 'active')
  const enrolledStudentIds = useMemo(() => new Set(enrollments.map((item) => String(item.student))), [enrollments])

  // Asistencia actual: viene YA en el detalle de clase (GymClassDetailSerializer →
  // `attendances`), no hace falta un GET aparte. Default visual 'absent' para el
  // alumno inscrito que todavía no tiene registro (mismo criterio que el profe en
  // TeacherClassesPage).
  useEffect(() => {
    if (!gymClass) {
      return
    }
    const attendanceByStudent = {}
    ;(gymClass.attendances || []).forEach((item) => {
      attendanceByStudent[item.student] = item.status
    })
    const draft = {}
    ;(gymClass.enrollments || [])
      .filter((item) => item.status === 'active')
      .forEach((item) => {
        draft[item.student] = attendanceByStudent[item.student] || 'absent'
      })
    setAttendanceMap(draft)
  }, [gymClass])

  const fetchAttendanceHistory = async () => {
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const data = await classesApi.getAttendanceHistory(id)
      setHistory(data)
    } catch (apiError) {
      setHistoryError(firstApiError(apiError?.response?.data, 'No se pudo cargar el historial de correcciones.'))
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    if (historyOpen) {
      fetchAttendanceHistory()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyOpen, id])

  const saveAttendance = async () => {
    if (activeEnrollments.length === 0) {
      return
    }
    setAttendanceSaving(true)
    setAttendanceError('')
    try {
      const payload = activeEnrollments.map((enrollment) => ({
        student_id: enrollment.student,
        status: attendanceMap[enrollment.student] || 'absent',
      }))
      await classesApi.saveAttendance(id, payload)
      await loadData()
      if (historyOpen) {
        await fetchAttendanceHistory()
      }
    } catch (apiError) {
      setAttendanceError(firstApiError(apiError?.response?.data, 'No se pudo guardar la asistencia.'))
    } finally {
      setAttendanceSaving(false)
    }
  }

  const filteredStudents = useMemo(() => {
    const query = search.trim().toLowerCase()
    return students.filter((student) => {
      if (enrolledStudentIds.has(String(student.id))) {
        return false
      }
      const fullName = `${student.first_name || ''} ${student.last_name || ''}`.trim()
      const matchText = `${fullName} ${student.username} ${student.email || ''}`.toLowerCase()
      return matchText.includes(query)
    })
  }, [students, search, enrolledStudentIds])

  const enrollStudent = async () => {
    if (!selectedStudentId) {
      return
    }
    setError('')
    try {
      await enrollmentsApi.create({
        gym_class: Number(id),
        student: Number(selectedStudentId),
        status: 'active',
      })
      setModalOpen(false)
      setSelectedStudentId('')
      setSearch('')
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      if (detail?.student?.[0]) {
        setError(detail.student[0])
      } else if (detail?.gym_class?.[0]) {
        setError(detail.gym_class[0])
      } else if (detail?.detail) {
        setError(detail.detail)
      } else {
        setError('No se pudo crear la inscripción.')
      }
    }
  }

  const removeEnrollment = async () => {
    if (!deleting) {
      return
    }
    await enrollmentsApi.remove(deleting.id)
    setDeleting(null)
    await loadData()
  }

  const columns = useMemo(
    () => [
      { key: 'student_name', label: 'Alumno' },
      { key: 'student_email', label: 'Email' },
      { key: 'status', label: 'Estado', render: (row) => <ValueBadge kind="enrollment_status" value={row.status} /> },
      ...(canManage
        ? [
            {
              key: 'actions',
              label: 'Acciones',
              render: (row) => (
                <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
                  Eliminar inscripción
                </button>
              ),
            },
          ]
        : []),
    ],
    [canManage],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Detalle de clase"
        subtitle={gymClass ? `${gymClass.name} · ${gymClass.branch_name}` : 'Cargando clase...'}
        back={{ to: '/gym-admin/classes', label: 'Clases' }}
        extra={
          canManage ? (
            <div className="flex gap-2">
              <button type="button" onClick={() => setModalOpen(true)} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
                Inscribir alumno
              </button>
              <Link to={`/gym-admin/classes/${id}/edit`} className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-muted">
                Editar clase
              </Link>
            </div>
          ) : null
        }
      />

      <section className="grid gap-4 md:grid-cols-5">
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Profesor</p>
          <p className="mt-1 font-semibold">{gymClass?.teacher_name || '-'}</p>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Tipo</p>
          <div className="mt-1">
            <ValueBadge kind="class_type" value={gymClass?.class_type_name} />
          </div>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Disciplina</p>
          <div className="mt-1">
            <ValueBadge kind="discipline" value={gymClass?.discipline_name} />
          </div>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Inicio</p>
          <p className="mt-1 font-semibold">{formatDateTime(gymClass?.start_datetime)}</p>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Cupos</p>
          <p className="mt-1 font-semibold">{`${activeEnrollments.length}/${gymClass?.capacity || 0}`}</p>
        </article>
      </section>

      <section className="card-surface p-5">
        <h2 className="panel-title mb-4">Alumnos inscritos</h2>
        <DataTable columns={columns} data={enrollments} loading={loading} />
      </section>

      <section className="card-surface p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="panel-title">Asistencia</h2>
          <button
            type="button"
            disabled={attendanceSaving || activeEnrollments.length === 0}
            onClick={saveAttendance}
            className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {attendanceSaving ? 'Guardando...' : 'Guardar asistencia'}
          </button>
        </div>

        {attendanceError ? (
          <p className="mb-3 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{attendanceError}</p>
        ) : null}

        {activeEnrollments.length === 0 ? (
          <p className="text-sm text-brand-muted">No hay alumnos inscritos activos en esta clase.</p>
        ) : (
          <div className="space-y-2">
            {activeEnrollments.map((enrollment) => (
              <div
                key={enrollment.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-line px-3 py-2 text-sm"
              >
                <span className="font-semibold">{enrollment.student_name}</span>
                <span className="flex items-center gap-2">
                  <ValueBadge kind="attendance_status" value={attendanceMap[enrollment.student]} />
                  <span className="flex gap-1">
                    {ATTENDANCE_TOGGLE_OPTIONS.map((option) => {
                      const selected = attendanceMap[enrollment.student] === option.value
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() =>
                            setAttendanceMap((prev) => ({
                              ...prev,
                              [enrollment.student]: option.value,
                            }))
                          }
                          className={`rounded-lg border px-2.5 py-1 text-xs transition ${
                            selected ? 'border-brand-blue bg-brand-blue/20 text-brand-white' : 'border-brand-line text-brand-muted hover:text-brand-white'
                          }`}
                        >
                          {option.label}
                        </button>
                      )
                    })}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card-surface p-5">
        <button
          type="button"
          onClick={() => setHistoryOpen((prev) => !prev)}
          className="flex w-full items-center justify-between gap-3 text-left"
        >
          <h2 className="panel-title">Historial de correcciones</h2>
          <span className="text-xs text-brand-muted">{historyOpen ? 'Ocultar ▲' : 'Ver ▼'}</span>
        </button>

        {historyOpen ? (
          <div className="mt-4">
            {historyLoading ? (
              <p className="text-sm text-brand-muted">Cargando historial...</p>
            ) : historyError ? (
              <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{historyError}</p>
            ) : history.length === 0 ? (
              <p className="text-sm text-brand-muted">Sin correcciones registradas.</p>
            ) : (
              <div className="space-y-2">
                {history.map((item) => (
                  <div key={item.id} className="rounded-lg border border-brand-line px-3 py-2 text-sm">
                    <p className="font-semibold">{item.student_name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <ValueBadge kind="attendance_status" value={item.previous_status} />
                      <span className="text-brand-muted">→</span>
                      <ValueBadge kind="attendance_status" value={item.new_status} />
                    </div>
                    <p className="mt-1 text-xs text-brand-muted">
                      {item.changed_by_username || '-'} · {formatDateTime(item.changed_at)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </section>

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title="Inscribir alumno">
        <div className="space-y-3">
          <label className="space-y-1 text-sm">
            <span>Buscar alumno</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Nombre, username o email"
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <div className="max-h-[22rem] space-y-2 overflow-y-auto rounded-lg border border-brand-line p-2 pr-1">
            {filteredStudents.length === 0 ? <p className="text-sm text-brand-muted">Sin resultados.</p> : null}
            {filteredStudents.map((student) => {
              const studentName = `${student.first_name || ''} ${student.last_name || ''}`.trim() || student.username
              return (
                <label key={student.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-brand-line px-3 py-2 text-sm">
                  <input
                    type="radio"
                    name="student"
                    checked={String(selectedStudentId) === String(student.id)}
                    onChange={() => setSelectedStudentId(student.id)}
                  />
                  <span>{studentName}</span>
                </label>
              )
            })}
          </div>

          {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

          <div className="flex justify-end">
            <button type="button" onClick={enrollStudent} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Confirmar inscripción
            </button>
          </div>
        </div>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar inscripción"
        description={`Se eliminará la inscripción de ${deleting?.student_name || 'este alumno'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeEnrollment}
      />
    </div>
  )
}
