import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { classesApi, enrollmentsApi, usersApi } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export default function GymAdminClassDetailPage() {
  const { id } = useParams()
  const [gymClass, setGymClass] = useState(null)
  const [students, setStudents] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedStudentId, setSelectedStudentId] = useState('')
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(null)

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
      {
        key: 'actions',
        label: 'Acciones',
        render: (row) => (
          <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
            Eliminar inscripción
          </button>
        ),
      },
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Detalle de clase"
        subtitle={gymClass ? `${gymClass.name} · ${gymClass.branch_name}` : 'Cargando clase...'}
        back={{ to: '/gym-admin/classes', label: 'Clases' }}
        extra={
          <div className="flex gap-2">
            <button type="button" onClick={() => setModalOpen(true)} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Inscribir alumno
            </button>
            <Link to={`/gym-admin/classes/${id}/edit`} className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-muted">
              Editar clase
            </Link>
          </div>
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
