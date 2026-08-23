import { useEffect, useMemo, useRef, useState } from 'react'
import { branchesApi, classTemplatesApi, classTypesApi, disciplinesApi, usersApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import BulkActionModal from '../components/BulkActionModal'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'
import MultiSelectDropdown from '../components/ui/MultiSelectDropdown'
import ValueBadge from '../components/ui/ValueBadge'
import { canManageAdmin, teacherEligibleRoleParam } from '../utils/roles'
import GymAdminClassesPage from './GymAdminClassesPage'

const initialForm = {
  name: '',
  description: '',
  branch: '',
  teacher: '',
  class_type: '',
  discipline: '',
  weekday: 0,
  weekdays: [],
  start_time: '',
  end_time: '',
  capacity: 20,
  is_active: true,
  is_trial_eligible: false,
  has_substitute: false,
  substitute_kind: 'external',
  substitute_teacher: '',
  substitute_name: '',
}

const weekdayLabels = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

const weekdayOptions = weekdayLabels.map((label, index) => ({ value: index, label }))

function formatTime(value) {
  return value?.slice(0, 5) || '-'
}

function formatTimeRange(start, end) {
  if (!start) {
    return '-'
  }
  return end ? `${formatTime(start)} - ${formatTime(end)}` : formatTime(start)
}

function firstApiError(detail) {
  if (!detail) {
    return null
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
  return 'No se pudo completar la operacion.'
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

export default function GymAdminClassTemplatesPage() {
  const { user } = useAuth()
  // Borrar una serie es solo de gym_admin/superadmin (el backend le da 403 al manager por
  // las dos vias, ver ClassTemplateViewSet). Sin esto el manager veia un boton y una accion
  // masiva que siempre fallaban.
  const canDeleteSeries = canManageAdmin(user?.role)
  const [form, setForm] = useState(initialForm)
  const [editingId, setEditingId] = useState(null)
  const [templates, setTemplates] = useState([])
  const [branches, setBranches] = useState([])
  const [teachers, setTeachers] = useState([])
  const [classTypes, setClassTypes] = useState([])
  const [disciplines, setDisciplines] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [workingId, setWorkingId] = useState(null)
  const [bulkWorking, setBulkWorking] = useState(false)
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('classes')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [deletingTemplate, setDeletingTemplate] = useState(null)
  // Marca en rojo el selector de dias tras un submit sin dias. El <select> nativo se autovalida
  // con "required"; un dropdown propio no, asi que el estado invalido es explicito.
  const [weekdaysInvalid, setWeekdaysInvalid] = useState(false)
  const firstFieldRef = useRef(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const [templatesData, branchesData, teachersData, classTypeData, disciplineData] = await Promise.all([
        classTemplatesApi.list({ ordering: 'start_date' }),
        branchesApi.list(),
        usersApi.list({ role: teacherEligibleRoleParam }),
        classTypesApi.list(),
        disciplinesApi.list(),
      ])
      setTemplates(templatesData)
      setBranches(branchesData)
      setTeachers(teachersData)
      setClassTypes(classTypeData)
      setDisciplines(disciplineData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const resetForm = () => {
    setForm(initialForm)
    setEditingId(null)
    setWeekdaysInvalid(false)
  }

  const focusForm = () => {
    window.setTimeout(() => {
      firstFieldRef.current?.focus?.()
    }, 0)
  }

  const openCreateForm = () => {
    setError('')
    setNotice('')
    resetForm()
    setActiveTab('schedule')
    setFormOpen(true)
    focusForm()
  }

  const closeForm = () => {
    if (saving) {
      return
    }
    setFormOpen(false)
    resetForm()
  }

  const startEdit = (row) => {
    setError('')
    setNotice('')
    setWeekdaysInvalid(false)
    setEditingId(row.id)
    setActiveTab('schedule')
    setFormOpen(true)
    setForm({
      name: row.name || '',
      description: row.description || '',
      branch: row.branch || '',
      teacher: row.teacher || '',
      class_type: row.class_type || '',
      discipline: row.discipline || '',
      weekday: row.weekday ?? 0,
      weekdays: [],
      start_time: row.start_time || '',
      end_time: row.end_time || '',
      capacity: row.capacity || 20,
      is_active: row.is_active,
      is_trial_eligible: Boolean(row.is_trial_eligible),
      has_substitute: Boolean(row.has_substitute),
      substitute_kind: row.substitute_teacher ? 'registered' : 'external',
      substitute_teacher: row.substitute_teacher ? String(row.substitute_teacher) : '',
      substitute_name: row.substitute_name || '',
    })
    focusForm()
  }

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')

    // El dropdown multi-dia no tiene "required" nativo (a diferencia del <select> singular que
    // reemplaza): validamos a mano antes de tocar la API.
    if (!editingId && form.weekdays.length === 0) {
      setError('Elegi al menos un dia.')
      setWeekdaysInvalid(true)
      return
    }
    setWeekdaysInvalid(false)

    setSaving(true)
    try {
      // weekday/weekdays nunca viajan juntos: creacion manda weekdays (lista), edicion manda
      // weekday (singular). Se separan del resto del form para no filtrar el que no corresponde.
      const { weekday, weekdays, substitute_kind, ...rest } = form
      const payload = {
        ...rest,
        ...substitutePayload(form),
        capacity: Number(form.capacity),
      }
      if (editingId) {
        await classTemplatesApi.update(editingId, {
          ...payload,
          weekday: Number(weekday),
          apply_to_future_instances: true,
        })
        setNotice('Clase actualizada. Se aplicaron cambios a las clases futuras editables.')
      } else {
        const data = await classTemplatesApi.create({
          ...payload,
          weekdays: weekdays.map(Number),
        })
        const created = data?.created || []
        const skipped = data?.skipped || []
        if (created.length > 0) {
          const skippedText = skipped.length ? ` ${skipped.length} ya existian y no se duplicaron.` : ''
          setNotice(`Se programaron ${created.length} clases semanales. Las clases se generan automaticamente.${skippedText}`)
        } else {
          setNotice(`No se programo ninguna clase nueva: los ${skipped.length} dias elegidos ya tenian una clase.`)
        }
      }
      resetForm()
      setFormOpen(false)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      setSaving(false)
    }
  }

  const toggleTemplate = async (row) => {
    setWorkingId(row.id)
    setError('')
    setNotice('')
    try {
      await classTemplatesApi.update(row.id, { is_active: !row.is_active })
      setNotice(row.is_active ? 'Clase desactivada.' : 'Clase activada.')
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      setWorkingId(null)
    }
  }

  const deleteTemplate = async () => {
    if (!deletingTemplate?.id) {
      return
    }

    setWorkingId(deletingTemplate.id)
    setError('')
    setNotice('')
    try {
      await classTemplatesApi.remove(deletingTemplate.id)
      setNotice('Clase eliminada correctamente.')
      setDeletingTemplate(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      setWorkingId(null)
    }
  }

  const runBulkAction = async ({ action, comment }) => {
    if (!selectedIds.length) {
      setError('Selecciona al menos una serie.')
      return
    }
    setError('')
    setNotice('')
    setBulkWorking(true)
    try {
      const payload = { action, template_ids: selectedIds }
      if (comment) {
        payload.comment = comment
      }
      const data = await classTemplatesApi.bulkAction(payload)
      const skipped = data.skipped || []
      const skippedText = skipped.length ? ` Bloqueadas: ${skipped.length}.` : ''
      setNotice(`Accion masiva completada. Actualizadas: ${data.updated_count || 0}. Eliminadas: ${data.deleted_count || 0}.${skippedText}`)
      setSelectedIds([])
      setBulkModalOpen(false)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      setBulkWorking(false)
    }
  }


  const columns = useMemo(
    () => [
      { key: 'name', label: 'Clase', render: (row) => row.name || `Clase #${row.id}` },
      { key: 'branch_name', label: 'Sucursal' },
      { key: 'teacher_name', label: 'Profesor' },
      {
        key: 'substitute_display_name',
        label: 'Suplente',
        mobile: 'hidden',
        render: (row) => (row.has_substitute ? row.substitute_display_name || row.substitute_name || '-' : <span className="text-brand-muted">Sin suplente</span>),
      },
      { key: 'class_type_name', label: 'Tipo', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      { key: 'weekday', label: 'Dia', render: (row) => weekdayLabels[row.weekday] || '-' },
      {
        key: 'start_time',
        label: 'Inicio',
        mobile: 'secondary',
        mobileLabel: 'Hora',
        mobilePriority: 1,
        render: (row) => formatTime(row.start_time),
        mobileRender: (row) => formatTimeRange(row.start_time, row.end_time),
      },
      { key: 'end_time', label: 'Termino', render: (row) => formatTime(row.end_time) },
      { key: 'start_date', label: 'Fecha inicio' },
      { key: 'end_date', label: 'Fecha fin', render: (row) => row.end_date || '-' },
      { key: 'capacity', label: 'Cupos' },
      { key: 'generated_instances_count', label: 'Instancias' },
      { key: 'is_active', label: 'Estado', render: (row) => <ValueBadge kind="template_status" value={row.is_active ? 'active' : 'inactive'} /> },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <>
            <button
              type="button"
              disabled={workingId === row.id}
              onClick={() => startEdit(row)}
              className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
            >
              Editar
            </button>
            <button
              type="button"
              disabled={workingId === row.id}
              onClick={() => toggleTemplate(row)}
              className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
            >
              {row.is_active ? 'Desactivar' : 'Activar'}
            </button>
            {canDeleteSeries ? (
              <button
                type="button"
                disabled={workingId === row.id}
                onClick={() => setDeletingTemplate(row)}
                className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 disabled:opacity-60"
              >
                Eliminar
              </button>
            ) : null}
          </>
        ),
      },
    ],
    [workingId, canDeleteSeries],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Gestión de clases"
        subtitle="Consulta clases reales por fecha y administra la programación semanal."
        extra={
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={openCreateForm} className="btn-primary">
              Crear clase
            </button>
          </div>
        }
      />

      <div className="flex flex-wrap gap-2 border-b border-brand-line">
        {[
          { value: 'classes', label: 'Clases' },
          { value: 'schedule', label: 'Programación' },
        ].map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setActiveTab(tab.value)}
            aria-current={activeTab === tab.value ? 'true' : undefined}
            className={`min-h-10 border-b-2 px-3 text-sm font-semibold transition ${
              activeTab === tab.value
                ? 'border-brand-orange text-brand-white'
                : 'border-transparent text-brand-muted hover:text-brand-white'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'classes' ? <GymAdminClassesPage embedded /> : null}

      {!formOpen && error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {!formOpen && notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}

      <FormModal
        open={formOpen}
        title={editingId ? 'Editar clase' : 'Crear clase'}
        onClose={closeForm}
        closeDisabled={saving}
        size="lg"
        variant="drawer"
      >
        <section className="space-y-3">
        <h2 className="panel-title">{editingId ? 'Editar clase' : 'Crear clase'}</h2>
        {editingId ? (
          <p className="rounded-lg border border-brand-orange/40 bg-brand-orange/10 px-3 py-2 text-sm text-brand-white">
            Editando clase #{editingId}. Guarda cambios o cancela la edicion para volver a crear.
          </p>
        ) : null}
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span>Nombre visible</span>
            <input ref={firstFieldRef} value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} className="field" />
          </label>
          {editingId ? (
            <label className="space-y-1 text-sm">
              <span>Dia semana</span>
              <select value={form.weekday} onChange={(event) => setForm((prev) => ({ ...prev, weekday: event.target.value }))} className="field">
                {weekdayLabels.map((label, index) => (
                  <option key={label} value={index}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <MultiSelectDropdown
              label="Dias de la semana"
              options={weekdayOptions}
              value={form.weekdays}
              onChange={(weekdays) => {
                setForm((prev) => ({ ...prev, weekdays }))
                if (weekdays.length > 0) {
                  setWeekdaysInvalid(false)
                }
              }}
              placeholder="Elegi uno o mas dias"
              allSelectedLabel="Todos los dias"
              invalid={weekdaysInvalid}
            />
          )}
          <label className="space-y-1 text-sm">
            <span>Sucursal</span>
            <select required value={form.branch} onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))} className="field">
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
            <select required value={form.teacher} onChange={(event) => setForm((prev) => ({ ...prev, teacher: event.target.value }))} className="field">
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
            <select required value={form.class_type} onChange={(event) => setForm((prev) => ({ ...prev, class_type: event.target.value }))} className="field">
              <option value="">Seleccionar</option>
              {classTypes.map((classType) => (
                <option key={classType.id} value={classType.id}>
                  {classType.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Disciplina</span>
            <select required value={form.discipline} onChange={(event) => setForm((prev) => ({ ...prev, discipline: event.target.value }))} className="field">
              <option value="">Seleccionar</option>
              {disciplines.map((discipline) => (
                <option key={discipline.id} value={discipline.id}>
                  {discipline.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Hora inicio</span>
            <input required type="time" value={form.start_time} onChange={(event) => setForm((prev) => ({ ...prev, start_time: event.target.value }))} className="field" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Hora termino</span>
            <input required type="time" value={form.end_time} onChange={(event) => setForm((prev) => ({ ...prev, end_time: event.target.value }))} className="field" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Capacidad</span>
            <input required min={1} type="number" value={form.capacity} onChange={(event) => setForm((prev) => ({ ...prev, capacity: event.target.value }))} className="field" />
          </label>
          {editingId ? null : (
            <p className="md:col-span-2 text-xs text-brand-muted">
              La clase arranca hoy y no tiene fecha de fin: se genera automaticamente cada semana hacia adelante.
            </p>
          )}
          <label className="space-y-1 text-sm md:col-span-2">
            <span>Descripcion (opcional)</span>
            <textarea value={form.description} onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))} className="field min-h-[80px]" />
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
                Las clases generadas desde esta plantilla podrán reservarse como prueba gratis desde el link público.
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
                  Define el suplente por defecto de la serie. Quien está asignado sigue siendo el titular para el pago; las clases nuevas que se generen heredan este valor.
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
                      className="field"
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
                      className="field"
                    />
                  </label>
                )}
              </div>
            ) : null}
          </div>
          <div className="md:col-span-2 flex justify-end gap-2">
            {editingId ? (
              <button type="button" onClick={closeForm} className="btn-ghost">
                Cancelar edicion
              </button>
            ) : null}
            <button type="submit" disabled={saving} className="btn-primary">
              {saving ? 'Guardando...' : editingId ? 'Guardar cambios' : 'Guardar y generar clases'}
            </button>
          </div>
        </form>
        {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
        {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}
        </section>
      </FormModal>

      {activeTab === 'schedule' ? (
        <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="panel-title">Clases programadas</h2>
          <button
            type="button"
            disabled={!selectedIds.length}
            onClick={() => setBulkModalOpen(true)}
            className="btn-ghost text-xs"
          >
            Acciones masivas ({selectedIds.length})
          </button>
        </div>
        <DataTable
          columns={columns}
          data={templates}
          loading={loading}
          selectableRows
          selectAllScope="filtered"
          selectedRowIds={selectedIds}
          onSelectedRowIdsChange={setSelectedIds}
          defaultSort={{ key: 'start_date', direction: 'asc' }}
        />
        </section>
      ) : null}

      <BulkActionModal
        open={bulkModalOpen}
        title="Acciones masivas de clases"
        selectedCount={selectedIds.length}
        loading={bulkWorking}
        actions={[
          { value: 'activate', label: 'Activar clases', description: 'Reanuda la clase para futuras generaciones.' },
          { value: 'deactivate', label: 'Desactivar clases', description: 'Detiene nuevas generaciones sin borrar historico.' },
          ...(canDeleteSeries
            ? [{ value: 'delete', label: 'Eliminar clases seguras', description: 'Elimina solo clases sin actividad bloqueante.' }]
            : []),
        ]}
        requiresCommentActions={[]}
        defaultAction="activate"
        onClose={() => setBulkModalOpen(false)}
        onConfirm={runBulkAction}
      />


      <ConfirmDialog
        open={Boolean(deletingTemplate)}
        title="Eliminar clase"
        description={`Eliminar clase ${deletingTemplate?.name || `#${deletingTemplate?.id || ''}`}? Solo se permite si no tiene historial ni inscritos.`}
        confirmLabel="Eliminar"
        loading={workingId === deletingTemplate?.id}
        onConfirm={deleteTemplate}
        onCancel={() => {
          if (!workingId) {
            setDeletingTemplate(null)
          }
        }}
      />
    </div>
  )
}
