import { useEffect, useMemo, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { classesApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import DashboardHeader from '../components/DashboardHeader'
import ValueBadge from '../components/ui/ValueBadge'
import { firstApiError } from '../utils/format'
import { formatDateTime } from './teacherClasses.helpers'

const ATTENDANCE_EDIT_GRACE_MINUTES = 20

function canToggleAttendance(user, gymClass) {
  if (!user || !gymClass || gymClass.status === 'cancelled') {
    return false
  }
  if (user.role === 'superadmin' || user.role === 'gym_admin') {
    return true
  }
  if (user.role === 'teacher') {
    const classEnd = new Date(gymClass.end_datetime).getTime()
    if (Number.isNaN(classEnd)) {
      return false
    }
    return Date.now() <= classEnd + ATTENDANCE_EDIT_GRACE_MINUTES * 60 * 1000
  }
  return false
}

export default function ClassAttendancePage() {
  const { id } = useParams()
  const location = useLocation()
  const { user } = useAuth()
  const [gymClass, setGymClass] = useState(null)
  const [students, setStudents] = useState([])
  const [attendanceMap, setAttendanceMap] = useState({})
  const [savingStudentId, setSavingStudentId] = useState(null)
  const [messages, setMessages] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const isTeacherRoute = location.pathname.startsWith('/teacher/')
  const back = isTeacherRoute
    ? { to: '/teacher/classes/all', label: 'Clases' }
    : { to: '/gym-admin/classes', label: 'Clases' }

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [classData, roster] = await Promise.all([
        classesApi.retrieve(id),
        classesApi.enrolledStudents(id),
      ])
      const draft = {}
      roster.forEach((student) => {
        draft[student.student_id] = student.attendance_status || 'absent'
      })
      setGymClass(classData)
      setStudents(roster)
      setAttendanceMap(draft)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la asistencia.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const canToggle = canToggleAttendance(user, gymClass)
  const presentCount = useMemo(
    () => students.filter((student) => attendanceMap[student.student_id] === 'present').length,
    [attendanceMap, students],
  )
  const absentCount = Math.max(students.length - presentCount, 0)

  const toggleStudent = async (student) => {
    if (!canToggle || savingStudentId) {
      return
    }

    const currentStatus = attendanceMap[student.student_id] || 'absent'
    const nextStatus = currentStatus === 'present' ? 'absent' : 'present'
    const previousStatus = currentStatus

    setSavingStudentId(student.student_id)
    setError('')
    setAttendanceMap((prev) => ({ ...prev, [student.student_id]: nextStatus }))
    setMessages((prev) => ({
      ...prev,
      [student.student_id]: nextStatus === 'present' ? 'Asistencia confirmada.' : 'Queda ausente.',
    }))

    try {
      const saved = await classesApi.toggleAttendance(id, {
        student_id: student.student_id,
        status: nextStatus,
      })
      setAttendanceMap((prev) => ({ ...prev, [student.student_id]: saved.status || nextStatus }))
    } catch (apiError) {
      setAttendanceMap((prev) => ({ ...prev, [student.student_id]: previousStatus }))
      setMessages((prev) => ({
        ...prev,
        [student.student_id]: 'No se pudo guardar.',
      }))
      setError(firstApiError(apiError?.response?.data, 'No se pudo guardar la asistencia.'))
    } finally {
      setSavingStudentId(null)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Asistencia"
        subtitle={
          gymClass
            ? `${gymClass.name} - ${gymClass.branch_name || '-'} - ${formatDateTime(gymClass.start_datetime)}`
            : 'Cargando clase...'
        }
        back={back}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <section className="grid grid-cols-3 gap-3">
        <article className="rounded-lg border border-brand-line bg-brand-panel/70 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Inscritos</p>
          <p className="mt-1 text-lg font-semibold text-brand-white">{students.length}</p>
        </article>
        <article className="rounded-lg border border-brand-line bg-brand-panel/70 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Presentes</p>
          <p className="mt-1 text-lg font-semibold text-brand-white">{presentCount}</p>
        </article>
        <article className="rounded-lg border border-brand-line bg-brand-panel/70 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Ausentes</p>
          <p className="mt-1 text-lg font-semibold text-brand-white">{absentCount}</p>
        </article>
      </section>

      {!canToggle && !loading ? (
        <p className="rounded-lg border border-brand-line bg-brand-panel/60 px-3 py-2 text-sm text-brand-muted">
          Vista de solo lectura para esta clase.
        </p>
      ) : null}

      <section className="space-y-3">
        {loading ? (
          <>
            <div className="h-20 animate-pulse rounded-lg bg-brand-line/50" />
            <div className="h-20 animate-pulse rounded-lg bg-brand-line/40" />
            <div className="h-20 animate-pulse rounded-lg bg-brand-line/30" />
          </>
        ) : null}

        {!loading && students.length === 0 ? (
          <p className="rounded-lg border border-brand-line bg-brand-panel/60 p-4 text-center text-sm text-brand-muted">
            No hay alumnos inscritos activos en esta clase.
          </p>
        ) : null}

        {students.map((student) => {
          const status = attendanceMap[student.student_id] || 'absent'
          const present = status === 'present'
          const saving = savingStudentId === student.student_id
          return (
            <article key={student.student_id} className="rounded-lg border border-brand-line bg-brand-panel/70 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-base font-semibold text-brand-white">{student.name}</p>
                  <p className="mt-1 truncate text-sm text-brand-muted">{student.email || student.username || '-'}</p>
                </div>
                <ValueBadge kind="attendance_status" value={status} />
              </div>

              <div className="mt-4 flex items-center justify-between gap-3">
                <p className="min-w-0 text-xs text-brand-muted">
                  {messages[student.student_id] || (present ? 'Asistencia confirmada.' : 'Sin confirmar: ausente.')}
                </p>
                <button
                  type="button"
                  aria-pressed={present}
                  disabled={!canToggle || savingStudentId !== null}
                  onClick={() => toggleStudent(student)}
                  className={`min-h-11 shrink-0 rounded-lg border px-4 py-2 text-sm font-semibold transition disabled:opacity-60 ${
                    present
                      ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-100'
                      : 'border-brand-blue/70 bg-brand-blue/15 text-brand-white hover:border-brand-blue'
                  }`}
                >
                  {saving ? 'Guardando...' : 'Confirmar'}
                </button>
              </div>
            </article>
          )
        })}
      </section>
    </div>
  )
}
