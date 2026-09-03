import { useEffect, useMemo, useState } from 'react'
import { classesApi, classTemplatesApi, enrollmentsApi } from '../api/client'
import { firstApiError } from '../utils/format'
import FormModal from './FormModal'
import PlanAlertBadge from './ui/PlanAlertBadge'

function BalanceBadge({ available, unlimited = false }) {
  const hasBalance = unlimited || Number(available || 0) > 0
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${hasBalance ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
      {unlimited ? 'Ilimitado' : hasBalance ? `${available} clases` : 'Sin saldo'}
    </span>
  )
}

function PlanStatusBadge({ student }) {
  return (
    <PlanAlertBadge
      level={student?.plan_expiry_alert_level}
      message={student?.plan_expiry_alert_message}
    />
  )
}

function studentMatchesSearch(student, rawQuery) {
  const query = rawQuery.trim().toLowerCase()
  if (!query) {
    return true
  }
  const text = `${student.name || ''} ${student.username || ''} ${student.email || ''}`.toLowerCase()
  return text.includes(query)
}

export default function ClassEnrollmentModal({
  open,
  gymClass,
  initialView = 'enroll',
  onClose,
  onChanged,
}) {
  const [view, setView] = useState(initialView)
  const [enrollStudents, setEnrollStudents] = useState([])
  const [enrolledStudents, setEnrolledStudents] = useState([])
  const [enrollSelectedIds, setEnrollSelectedIds] = useState([])
  const [enrolledSelectedIds, setEnrolledSelectedIds] = useState([])
  const [enrollSearch, setEnrollSearch] = useState('')
  const [enrolledSearch, setEnrolledSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  // Una fila `virtual:<serie>:<fecha>` es una clase PROYECTADA: la serie dice que ese dia hay
  // clase, pero todavia no existe la fila en la BD. El modal sabe operar sobre eso sin
  // crearla: mirar a quien se podria inscribir no puede tener el efecto de materializar.
  const projectedParts = String(gymClass?.id || '').split(':')
  const isProjected = projectedParts[0] === 'virtual' && projectedParts.length === 3
  const projectedDate = isProjected ? projectedParts[2] : ''
  const templateId = gymClass?.class_template

  // La primera inscripcion hace nacer la clase. Desde ahi el modal deja de hablarle a la
  // serie y pasa a la PK real, para que quitar inscritos y recargar funcionen igual que
  // sobre una clase de siempre.
  const [materializedId, setMaterializedId] = useState(null)
  const classId = materializedId || (isProjected ? null : gymClass?.id)

  const loadRoster = async (targetId = classId) => {
    if (!targetId && !(isProjected && templateId)) {
      return
    }

    setLoading(true)
    setError('')
    try {
      if (!targetId) {
        // Clase inexistente: los candidatos salen de la serie y no hay inscritos que leer.
        const candidates = await classTemplatesApi.enrollableStudents(templateId)
        setEnrollStudents(candidates)
        setEnrolledStudents([])
      } else {
        const [candidates, enrolled] = await Promise.all([
          classesApi.enrollableStudents(targetId),
          classesApi.enrolledStudents(targetId),
        ])
        setEnrollStudents(candidates)
        setEnrolledStudents(enrolled)
      }
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la lista de alumnos.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) {
      return
    }
    setView(initialView)
    setMaterializedId(null)
    setEnrollSelectedIds([])
    setEnrolledSelectedIds([])
    setEnrollSearch('')
    setEnrolledSearch('')
    loadRoster()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, classId, initialView])

  const filteredEnrollStudents = useMemo(
    () => enrollStudents.filter((student) => studentMatchesSearch(student, enrollSearch)),
    [enrollSearch, enrollStudents],
  )
  const filteredEnrolledStudents = useMemo(
    () => enrolledStudents.filter((student) => studentMatchesSearch(student, enrolledSearch)),
    [enrolledSearch, enrolledStudents],
  )

  const submitEnrollments = async () => {
    if ((!classId && !(isProjected && templateId)) || enrollSelectedIds.length === 0) {
      return
    }

    const selectedStudents = enrollStudents.filter((student) => enrollSelectedIds.includes(student.id))
    const withoutBalance = selectedStudents.filter((student) => !student.has_available_classes)
    if (withoutBalance.length > 0) {
      setError('Alumno sin clases disponibles.')
      return
    }

    setWorking(true)
    setError('')
    try {
      // Sobre una clase proyectada se manda `class_template_id` + `date`: es el MISMO
      // contrato que ya usa el alumno al reservar, y materializa e inscribe en un solo acto,
      // asi que el descuento del plan ocurre junto con la inscripcion y no antes. El
      // `get_or_create` del backend es idempotente, por eso todo el lote puede mandar la
      // misma referencia de serie sin duplicar la clase.
      let realClassId = classId
      for (const studentId of enrollSelectedIds) {
        // eslint-disable-next-line no-await-in-loop
        const created = await enrollmentsApi.create(
          realClassId
            ? { gym_class: realClassId, student: studentId, status: 'active' }
            : { class_template_id: templateId, date: projectedDate, student: studentId, status: 'active' },
        )
        realClassId = realClassId || created?.gym_class || null
      }
      if (realClassId && realClassId !== classId) {
        setMaterializedId(realClassId)
      }
      setEnrollSelectedIds([])
      setEnrollSearch('')
      await loadRoster(realClassId)
      await onChanged?.()
      onClose?.()
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
    if (!classId || enrolledSelectedIds.length === 0) {
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
      await loadRoster()
      await onChanged?.()
      onClose?.()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron quitar los alumnos seleccionados.'))
    } finally {
      setWorking(false)
    }
  }

  const close = () => {
    if (working) {
      return
    }
    onClose?.()
  }

  return (
    <FormModal
      open={open}
      closeDisabled={working}
      onClose={close}
      title={gymClass ? `${view === 'enroll' ? 'Inscribir alumnos' : 'Ver inscritos'} - ${gymClass.name}` : 'Inscripciones'}
    >
      <div className="space-y-3">
        {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

        <div className="inline-flex rounded-lg border border-brand-line bg-black/20 p-1">
          <button
            type="button"
            onClick={() => setView('enroll')}
            className={`rounded-md px-3 py-1.5 text-sm font-semibold transition ${view === 'enroll' ? 'bg-brand-blue/20 text-brand-white' : 'text-brand-muted hover:text-brand-white'}`}
          >
            Inscribir
          </button>
          <button
            type="button"
            onClick={() => setView('enrolled')}
            className={`rounded-md px-3 py-1.5 text-sm font-semibold transition ${view === 'enrolled' ? 'bg-brand-blue/20 text-brand-white' : 'text-brand-muted hover:text-brand-white'}`}
          >
            Inscritos
          </button>
        </div>

        {view === 'enroll' ? (
          <>
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
              {loading ? <p className="text-sm text-brand-muted">Cargando alumnos...</p> : null}
              {!loading && filteredEnrollStudents.map((student) => (
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
              {!loading && enrollStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay alumnos disponibles para inscribir.</p> : null}
              {!loading && enrollStudents.length > 0 && filteredEnrollStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay resultados para la busqueda.</p> : null}
            </div>

            <div className="flex justify-end">
              <button
                type="button"
                disabled={working || loading || enrollSelectedIds.length === 0}
                onClick={submitEnrollments}
                className="btn-primary"
              >
                {working ? 'Inscribiendo...' : 'Inscribir seleccionados'}
              </button>
            </div>
          </>
        ) : (
          <>
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
              {loading ? <p className="text-sm text-brand-muted">Cargando inscritos...</p> : null}
              {!loading && filteredEnrolledStudents.map((student) => (
                <label key={student.enrollment_id} className="flex items-center justify-between gap-3 rounded-lg border border-brand-line px-3 py-2 text-sm">
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
                    checked={enrolledSelectedIds.includes(student.enrollment_id)}
                    onChange={(event) =>
                      setEnrolledSelectedIds((prev) =>
                        event.target.checked ? [...prev, student.enrollment_id] : prev.filter((id) => id !== student.enrollment_id),
                      )
                    }
                  />
                </label>
              ))}
              {!loading && enrolledStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay alumnos inscritos en esta clase.</p> : null}
              {!loading && enrolledStudents.length > 0 && filteredEnrolledStudents.length === 0 ? <p className="text-sm text-brand-muted">No hay resultados para la busqueda.</p> : null}
            </div>

            <div className="flex justify-end gap-2">
              <button type="button" disabled={working || loading} onClick={() => setView('enroll')} className="btn-ghost">
                Inscribir alumnos
              </button>
              <button
                type="button"
                disabled={working || loading || enrolledSelectedIds.length === 0}
                onClick={removeSelectedEnrollments}
                className="btn-danger"
              >
                {working ? 'Quitando...' : 'Quitar seleccionados'}
              </button>
            </div>
          </>
        )}
      </div>
    </FormModal>
  )
}
