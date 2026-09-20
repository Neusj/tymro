import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { useLocation, useParams } from 'react-router-dom'
import { attendanceQrApi, classesApi, enrollmentsApi, studentQrApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ClassEnrollmentModal from '../components/ClassEnrollmentModal'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import QrCameraScanner from '../components/QrCameraScanner'
import ValueBadge from '../components/ui/ValueBadge'
import { firstApiError } from '../utils/format'
import { canManageOperational } from '../utils/roles'
import { formatDateTime } from './teacherClasses.helpers'

function canToggleAttendance(user, gymClass) {
  if (!user || !gymClass || ['cancelled', 'suspended'].includes(gymClass.status)) {
    return false
  }
  if (user.role === 'superadmin' || user.role === 'gym_admin') {
    return true
  }
  if (user.role === 'teacher') {
    const classEnd = new Date(gymClass.end_datetime).getTime()
    const limitMinutes = Number(gymClass.teacher_attendance_edit_limit_minutes)
    if (Number.isNaN(classEnd) || !Number.isFinite(limitMinutes) || limitMinutes < 0) {
      return false
    }
    return Date.now() <= classEnd + limitMinutes * 60 * 1000
  }
  return false
}

function canEnrollFromAttendance(user, gymClass) {
  if (!user || !gymClass || ['cancelled', 'suspended'].includes(gymClass.status)) {
    return false
  }
  if (canManageOperational(user.role)) {
    return true
  }
  if (user.role !== 'teacher') {
    return false
  }
  const classEnd = new Date(gymClass.end_datetime).getTime()
  const limitMinutes = Number(gymClass.teacher_enrollment_edit_limit_minutes)
  if (Number.isNaN(classEnd) || !Number.isFinite(limitMinutes) || limitMinutes < 0) {
    return false
  }
  return Date.now() <= classEnd + limitMinutes * 60 * 1000
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
  const [enrollmentModalOpen, setEnrollmentModalOpen] = useState(false)
  const [classId, setClassId] = useState(id)
  const [classQrOpen, setClassQrOpen] = useState(false)
  const [classQrImage, setClassQrImage] = useState('')
  const [scannerOpen, setScannerOpen] = useState(false)
  const [scanResult, setScanResult] = useState(null)
  const [scanError, setScanError] = useState('')

  const isTeacherRoute = location.pathname.startsWith('/teacher/')
  const backTo = location.state?.classListBackTo
  const back = isTeacherRoute
    ? { to: backTo?.pathname ? `${backTo.pathname}${backTo.search || ''}` : '/teacher/classes/upcoming', label: 'Volver', state: location.state }
    : { to: backTo?.pathname ? `${backTo.pathname}${backTo.search || ''}` : '/gym-admin/classes', label: 'Volver', state: location.state }

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const resolved = await classesApi.resolveProjection(id)
      const resolvedId = resolved.id
      const [classData, roster] = await Promise.all([
        classesApi.retrieve(resolvedId),
        classesApi.enrolledStudents(resolvedId),
      ])
      const draft = {}
      roster.forEach((student) => {
        draft[student.student_id] = student.attendance_status || 'absent'
      })
      setGymClass(classData)
      setClassId(resolvedId)
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
  const canManageEnrollments = canEnrollFromAttendance(user, gymClass)
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
      const saved = await classesApi.toggleAttendance(classId, {
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

  const openClassQr = async () => {
    setError('')
    try {
      const data = await attendanceQrApi.current({ class_id: classId })
      setClassQrImage(await QRCode.toDataURL(data.check_in_url, { width: 420, margin: 2 }))
      setClassQrOpen(true)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo generar el QR de asistencia.'))
    }
  }

  const decodeStudentQr = async (token) => {
    setScanError('')
    try {
      const result = await studentQrApi.resolveForClass(classId, token.trim())
      setScanResult(result)
    } catch (apiError) {
      setScanError(firstApiError(apiError?.response?.data, 'No se pudo identificar el alumno.'))
    }
  }

  const markScannedStudent = async () => {
    if (!scanResult) return
    const nextStatus = scanResult.attendance_status === 'present' ? 'absent' : 'present'
    try {
      await classesApi.toggleAttendance(classId, { student_id: scanResult.student.id, status: nextStatus })
      setScanResult((prev) => ({ ...prev, attendance_status: nextStatus }))
      loadData()
    } catch (apiError) {
      setScanError(firstApiError(apiError?.response?.data, 'No se pudo guardar la asistencia.'))
    }
  }

  const enrollScannedStudent = async () => {
    if (!scanResult) return
    try {
      // El endpoint existente centraliza cupo, estado, sede, vigencia y FEFO.
      await enrollmentsApi.create({ gym_class: classId, student: scanResult.student.id })
      const next = { ...scanResult, enrolled: true, attendance_status: null }
      setScanResult(next)
      await classesApi.toggleAttendance(classId, { student_id: next.student.id, status: 'present' })
      setScanResult({ ...next, attendance_status: 'present' })
      loadData()
    } catch (apiError) {
      setScanError(firstApiError(apiError?.response?.data, 'No se pudo inscribir al alumno.'))
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
        extra={
          <div className="flex gap-2">
            {['teacher', 'gym_admin'].includes(user?.role) ? <button type="button" onClick={openClassQr} className="btn-ghost">Mostrar QR</button> : null}
            {canManageEnrollments ? <button type="button" onClick={() => setEnrollmentModalOpen(true)} className="btn-primary">Inscribir alumno</button> : null}
            {canToggle ? <button type="button" onClick={() => { setScannerOpen(true); setScanResult(null); setScanError('') }} className="btn-primary">Escanear alumno</button> : null}
          </div>
        }
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
                      ? 'border-brand-red/60 bg-brand-red/10 text-red-100 hover:border-brand-red'
                      : 'border-brand-blue/70 bg-brand-blue/15 text-brand-white hover:border-brand-blue'
                  }`}
                >
                  {saving ? 'Guardando...' : present ? 'Quitar' : 'Confirmar'}
                </button>
              </div>
            </article>
          )
        })}
      </section>

      <ClassEnrollmentModal
        open={enrollmentModalOpen}
        gymClass={gymClass}
        initialView="enroll"
        onClose={() => setEnrollmentModalOpen(false)}
        onChanged={loadData}
      />

      <FormModal open={classQrOpen} title="QR de asistencia" onClose={() => setClassQrOpen(false)}>
        <p className="text-sm text-brand-muted">Los alumnos inscritos pueden escanearlo para marcar asistencia.</p>
        {classQrImage ? <img src={classQrImage} alt="QR de asistencia de la clase" className="mx-auto mt-4 w-full max-w-sm rounded-xl bg-white p-3" /> : null}
      </FormModal>

      <FormModal open={scannerOpen} title="Escanear carnet QR" onClose={() => setScannerOpen(false)} size="lg">
        {!scanResult ? <QrCameraScanner onDecode={decodeStudentQr} paused={Boolean(scanError)} /> : null}
        {scanError ? <p className="mt-3 text-sm text-brand-red">{scanError}</p> : null}
        {!scanResult && scanError ? <button type="button" className="btn-ghost mt-3" onClick={() => setScanError('')}>Reintentar</button> : null}
        {scanResult ? (
          <div className="space-y-4">
            <p className="text-lg font-semibold text-brand-white">{scanResult.student.name}</p>
            {scanResult.enrolled ? (
              <button type="button" className="btn-primary" onClick={markScannedStudent}>
                {scanResult.attendance_status === 'present' ? 'Quitar asistencia' : 'Marcar asistencia'}
              </button>
            ) : (
              <button type="button" className="btn-primary" onClick={enrollScannedStudent}>Inscribir y marcar asistencia</button>
            )}
            <button type="button" className="btn-ghost" onClick={() => { setScanResult(null); setScanError('') }}>Escanear otro</button>
          </div>
        ) : null}
      </FormModal>
    </div>
  )
}
