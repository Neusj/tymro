// TODO unificacion: esta pantalla puntual queda inerte, decidir en el rediseno si se elimina o se
// fusiona con la de series (GymAdminClassTemplatesPage). Ya no se llega por navegacion: el boton
// "Crear clase" del listado apunta a /gym-admin/class-templates. La ruta sigue registrada en
// App.jsx (acceso directo por URL + e2e/tests/27-gym-admin-classes.spec.js) y el endpoint
// POST /api/classes/ sigue vivo para el importador y la edicion.

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { branchesApi, classTypesApi, classesApi, disciplinesApi, usersApi } from '../api/client'
import { teacherEligibleRoleParam } from '../utils/roles'
import DashboardHeader from '../components/DashboardHeader'

const initialForm = {
  name: '',
  branch: '',
  teacher: '',
  class_type: '',
  discipline: '',
  start_datetime: '',
  end_datetime: '',
  capacity: 10,
  is_trial_eligible: false,
  has_substitute: false,
  substitute_kind: 'external',
  substitute_teacher: '',
  substitute_name: '',
}

function substitutePayload(form) {
  if (!form.has_substitute) {
    return { has_substitute: false, substitute_teacher: null, substitute_name: '' }
  }
  if (form.substitute_kind === 'registered') {
    return { has_substitute: true, substitute_teacher: Number(form.substitute_teacher), substitute_name: '' }
  }
  return { has_substitute: true, substitute_teacher: null, substitute_name: form.substitute_name }
}

export default function GymAdminClassCreatePage() {
  const navigate = useNavigate()
  const [form, setForm] = useState(initialForm)
  const [branches, setBranches] = useState([])
  const [teachers, setTeachers] = useState([])
  const [classTypes, setClassTypes] = useState([])
  const [disciplines, setDisciplines] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const loadData = async () => {
    const [branchesData, teachersData, classTypeData, disciplineData] = await Promise.all([
      branchesApi.list(),
      usersApi.list({ role: teacherEligibleRoleParam }),
      classTypesApi.list(),
      disciplinesApi.list(),
    ])
    setBranches(branchesData)
    setTeachers(teachersData)
    // Al crear una clase solo ofrecemos tipos/disciplinas activos. (is_active !== false
    // mantiene compatibilidad con registros previos sin el campo.)
    setClassTypes((classTypeData || []).filter((item) => item.is_active !== false))
    setDisciplines((disciplineData || []).filter((item) => item.is_active !== false))
  }

  useEffect(() => {
    loadData()
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')

    try {
      const { substitute_kind, ...formPayload } = form
      await classesApi.create({
        ...formPayload,
        ...substitutePayload(form),
        capacity: Number(form.capacity),
      })
      navigate('/gym-admin/classes')
    } catch (apiError) {
      const detail = apiError?.response?.data
      if (typeof detail === 'string') {
        setError(detail)
      } else if (detail?.detail) {
        setError(detail.detail)
      } else {
        setError('No se pudo crear la clase. Revisa los campos ingresados.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Crear Clase"
        subtitle="Programa una nueva clase con profesor, tipo y cupos."
        back={{ to: '/gym-admin/class-templates', label: 'Gestión de clases' }}
      />

      <section className="card-surface p-5">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm md:col-span-2">
            <span>Nombre</span>
            <input
              required
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>

          <label className="space-y-1 text-sm">
            <span>Sucursal</span>
            <select
              required
              value={form.branch}
              onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar</option>
              {branches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-sm">
            <span>Profesor</span>
            <select
              required
              value={form.teacher}
              onChange={(event) => setForm((prev) => ({ ...prev, teacher: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar</option>
              {teachers.map((teacher) => (
                <option key={teacher.id} value={teacher.id}>
                  {`${teacher.first_name || ''} ${teacher.last_name || ''}`.trim() || teacher.username}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-sm">
            <span>Tipo</span>
            <select
              required
              value={form.class_type}
              onChange={(event) => setForm((prev) => ({ ...prev, class_type: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar</option>
              {classTypes.map((classType) => (
                <option key={classType.id} value={classType.id}>
                  {classType.name}
                </option>
              ))}
            </select>
            <div className="mt-2">
              <Link to="/gym-admin/class-types" className="text-xs text-brand-blue hover:underline">
                Gestionar tipos
              </Link>
            </div>
          </label>

          <label className="space-y-1 text-sm">
            <span>Disciplina</span>
            <select
              required
              value={form.discipline}
              onChange={(event) => setForm((prev) => ({ ...prev, discipline: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar</option>
              {disciplines.map((discipline) => (
                <option key={discipline.id} value={discipline.id}>
                  {discipline.name}
                </option>
              ))}
            </select>
            <div className="mt-2">
              <Link to="/gym-admin/disciplines" className="text-xs text-brand-blue hover:underline">
                Gestionar disciplinas
              </Link>
            </div>
          </label>

          <label className="space-y-1 text-sm">
            <span>Inicio</span>
            <input
              required
              type="datetime-local"
              value={form.start_datetime}
              onChange={(event) => setForm((prev) => ({ ...prev, start_datetime: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>

          <label className="space-y-1 text-sm">
            <span>Término</span>
            <input
              required
              type="datetime-local"
              value={form.end_datetime}
              onChange={(event) => setForm((prev) => ({ ...prev, end_datetime: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>

          <label className="space-y-1 text-sm">
            <span>Cupos</span>
            <input
              required
              min={1}
              type="number"
              value={form.capacity}
              onChange={(event) => setForm((prev) => ({ ...prev, capacity: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>

          <label className="md:col-span-2 flex items-start gap-3 rounded-lg border border-brand-line bg-black/20 px-3 py-3 text-sm">
            <input
              type="checkbox"
              checked={form.is_trial_eligible}
              onChange={(event) => setForm((prev) => ({ ...prev, is_trial_eligible: event.target.checked }))}
              className="mt-0.5 h-4 w-4 shrink-0 accent-brand-orange"
            />
            <span>
              <span className="font-semibold text-brand-white">Elegible para clase de prueba gratis</span>
              <span className="mt-0.5 block text-xs text-brand-muted">
                Los prospectos que se registran por el link público podrán reservar esta clase como su prueba gratis.
              </span>
            </span>
          </label>

          <div className="md:col-span-2 space-y-3 rounded-lg border border-brand-line bg-black/20 px-3 py-3 text-sm">
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={form.has_substitute}
                onChange={(event) => {
                  const checked = event.target.checked
                  // Al desmarcar, se limpia el nombre: no puede quedar un suplente
                  // "fantasma" cargado si el check se apaga (mismo invariante que exige
                  // el backend).
                  setForm((prev) => ({
                    ...prev,
                    has_substitute: checked,
                    substitute_teacher: checked ? prev.substitute_teacher : '',
                    substitute_name: checked ? prev.substitute_name : '',
                  }))
                }}
                className="mt-0.5 h-4 w-4 shrink-0 accent-brand-orange"
              />
              <span>
                <span className="font-semibold text-brand-white">Clase con suplente</span>
                <span className="mt-0.5 block text-xs text-brand-muted">
                  Quien está asignado sigue siendo el titular para el pago. El suplente es solo un registro de quién dio la clase.
                </span>
              </span>
            </label>
            {form.has_substitute ? (
              <div className="space-y-3 pl-7">
                <fieldset className="flex flex-wrap gap-3 text-sm">
                  <legend className="sr-only">Tipo de suplente</legend>
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="substitute_kind"
                      value="registered"
                      checked={form.substitute_kind === 'registered'}
                      onChange={() => setForm((prev) => ({ ...prev, substitute_kind: 'registered', substitute_name: '' }))}
                    />
                    <span>Profesor registrado</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="substitute_kind"
                      value="external"
                      checked={form.substitute_kind === 'external'}
                      onChange={() => setForm((prev) => ({ ...prev, substitute_kind: 'external', substitute_teacher: '' }))}
                    />
                    <span>Externo</span>
                  </label>
                </fieldset>
                {form.substitute_kind === 'registered' ? (
                  <label className="block space-y-1 text-sm">
                    <span>Profesor suplente</span>
                    <select
                      required
                      value={form.substitute_teacher}
                      onChange={(event) => setForm((prev) => ({ ...prev, substitute_teacher: event.target.value }))}
                      className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                    >
                      <option value="">Seleccionar</option>
                      {teachers
                        .filter((teacher) => String(teacher.id) !== String(form.teacher))
                        .map((teacher) => (
                          <option key={teacher.id} value={teacher.id}>
                            {`${teacher.first_name || ''} ${teacher.last_name || ''}`.trim() || teacher.username}
                          </option>
                        ))}
                    </select>
                  </label>
                ) : (
                  <label className="block space-y-1 text-sm">
                    <span>Nombre del suplente externo</span>
                    <input
                      required
                      value={form.substitute_name}
                      onChange={(event) => setForm((prev) => ({ ...prev, substitute_name: event.target.value }))}
                      placeholder="Nombre y apellido"
                      className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                    />
                  </label>
                )}
              </div>
            ) : null}
          </div>

          {error ? <p className="md:col-span-2 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

          <div className="md:col-span-2 flex justify-end">
            <button type="submit" disabled={saving} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {saving ? 'Guardando...' : 'Crear clase'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
