import { useEffect, useMemo, useState } from 'react'
import { advanceClassWindowsApi, branchesApi, classTemplatesApi, classTypesApi, disciplinesApi, usersApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import BulkActionModal from '../components/BulkActionModal'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { canManageAdmin } from '../utils/roles'

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
}

const weekdayLabels = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

function formatTime(value) {
  return value?.slice(0, 5) || '-'
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

export default function GymAdminClassTemplatesPage() {
  const { user } = useAuth()
  // Borrar una serie es solo de gym_admin/superadmin (el backend le da 403 al manager por
  // las dos vias, ver ClassTemplateViewSet). Sin esto el manager veia un boton y una accion
  // masiva que siempre fallaban.
  const canDeleteSeries = canManageAdmin(user?.role)
  // El robot de ventana rodante es SOLO gym_admin (ni manager ni superadmin, ver
  // AdvanceClassWindowsView.post en el backend): mueve saldo real de alumnos y borra
  // clases sin vuelta atras, asi que no reutiliza canManageAdmin/canManageOperational.
  // Esto es cosmetico; la autorizacion real es el 403 del backend.
  const canAdvanceClassWindows = user?.role === 'gym_admin'
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
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirmingAdvance, setConfirmingAdvance] = useState(false)
  const [advancingWindows, setAdvancingWindows] = useState(false)

  const loadData = async () => {
    setLoading(true)
    try {
      const [templatesData, branchesData, teachersData, classTypeData, disciplineData] = await Promise.all([
        classTemplatesApi.list({ ordering: 'start_date' }),
        branchesApi.list(),
        usersApi.list({ role: 'teacher' }),
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
  }

  const startEdit = (row) => {
    setError('')
    setNotice('')
    setEditingId(row.id)
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
    })
  }

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')

    // Los checkboxes de dias no tienen "required" nativo de grupo (a diferencia del <select>
    // singular que reemplazan): validamos a mano antes de tocar la API.
    if (!editingId && form.weekdays.length === 0) {
      setError('Elegi al menos un dia.')
      return
    }

    setSaving(true)
    try {
      // weekday/weekdays nunca viajan juntos: creacion manda weekdays (lista), edicion manda
      // weekday (singular). Se separan del resto del form para no filtrar el que no corresponde.
      const { weekday, weekdays, ...rest } = form
      const payload = {
        ...rest,
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

  const generateInstances = async (row) => {
    setWorkingId(row.id)
    setError('')
    setNotice('')
    try {
      const data = await classTemplatesApi.generate(row.id, {
        from_date: row.start_date,
        until_date: row.end_date || null,
      })
      setNotice(`Generacion completada: ${data.created_count || 0} nuevas clases.`)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      setWorkingId(null)
    }
  }

  const reactivateFutureCancelled = async (row) => {
    setWorkingId(row.id)
    setError('')
    setNotice('')
    try {
      const data = await classTemplatesApi.reactivateFutureCancelled(row.id)
      setNotice(`Reactivacion completada: ${data.reactivated_count || 0} clases futuras reactivadas.`)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      setWorkingId(null)
    }
  }

  const deleteTemplate = async (row) => {
    const confirmed = window.confirm(`Eliminar clase ${row.name || `#${row.id}`}? Solo se permite si no tiene historial ni inscritos.`)
    if (!confirmed) {
      return
    }

    setWorkingId(row.id)
    setError('')
    setNotice('')
    try {
      await classTemplatesApi.remove(row.id)
      setNotice('Clase eliminada correctamente.')
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

  const runAdvanceClassWindows = async () => {
    setAdvancingWindows(true)
    setError('')
    setNotice('')
    try {
      const data = await advanceClassWindowsApi.run()
      const created = data.instances_created || 0
      const pruned = data.pruned_count || 0
      const warningsText = data.errors?.length ? `, con ${data.errors.length} avisos` : ''
      setNotice(`Se generaron ${created} clases, se eliminaron ${pruned} clases vacías${warningsText}.`)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data))
    } finally {
      // Incondicional (éxito Y error): el ConfirmDialog es un portal full-viewport con backdrop
      // opaco que tapa el banner de error de la página. Si solo cerrara en el path de éxito, un
      // 403 (org suspendida a mitad de sesión) dejaría al admin mirando el diálogo sin feedback
      // visible, creyendo que no pasó nada. Mismo patrón que
      // GymAdminPaymentsSettingsPage.handleDisconnect (setConfirmingDisconnect en finally).
      setConfirmingAdvance(false)
      setAdvancingWindows(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'name', label: 'Clase', render: (row) => row.name || `Clase #${row.id}` },
      { key: 'branch_name', label: 'Sucursal' },
      { key: 'teacher_name', label: 'Profesor' },
      { key: 'class_type_name', label: 'Tipo', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      { key: 'weekday', label: 'Dia', render: (row) => weekdayLabels[row.weekday] || '-' },
      { key: 'start_time', label: 'Inicio', render: (row) => formatTime(row.start_time) },
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
              onClick={() => generateInstances(row)}
              className="w-full rounded-lg border border-brand-blue px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
            >
              Generar clases
            </button>
            <button
              type="button"
              disabled={workingId === row.id}
              onClick={() => toggleTemplate(row)}
              className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
            >
              {row.is_active ? 'Desactivar' : 'Activar'}
            </button>
            <button
              type="button"
              disabled={workingId === row.id}
              onClick={() => reactivateFutureCancelled(row)}
              className="w-full rounded-lg border border-brand-orange/60 px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
            >
              Reactivar futuras canceladas
            </button>
            {canDeleteSeries ? (
              <button
                type="button"
                disabled={workingId === row.id}
                onClick={() => deleteTemplate(row)}
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
        title="Gym Admin · Crear Clase"
        subtitle="Programa una nueva clase con profesor, tipo y cupos. Se repite cada semana en los dias que elijas y las clases se generan automaticamente desde hoy."
        back={{ to: '/gym-admin/classes', label: 'Clases' }}
        extra={
          canAdvanceClassWindows ? (
            <button
              type="button"
              disabled={advancingWindows}
              onClick={() => setConfirmingAdvance(true)}
              className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {advancingWindows ? 'Actualizando...' : 'Actualizar clases'}
            </button>
          ) : null
        }
      />

      <section className="card-surface p-5 space-y-3">
        <h2 className="panel-title">{editingId ? 'Editar clase' : 'Crear clase'}</h2>
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span>Nombre visible</span>
            <input value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          {editingId ? (
            <label className="space-y-1 text-sm">
              <span>Dia semana</span>
              <select value={form.weekday} onChange={(event) => setForm((prev) => ({ ...prev, weekday: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
                {weekdayLabels.map((label, index) => (
                  <option key={label} value={index}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="space-y-1 text-sm md:col-span-2">
              <span>Dias de la semana</span>
              <div className="flex flex-wrap gap-2">
                {weekdayLabels.map((label, index) => {
                  const checked = form.weekdays.includes(index)
                  return (
                    <label key={label} className="flex items-center gap-1.5 rounded-lg border border-brand-line bg-black/20 px-2.5 py-1.5 text-xs">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) =>
                          setForm((prev) => ({
                            ...prev,
                            weekdays: event.target.checked
                              ? [...prev.weekdays, index].sort((a, b) => a - b)
                              : prev.weekdays.filter((day) => day !== index),
                          }))
                        }
                        className="h-4 w-4 accent-brand-orange"
                      />
                      {label}
                    </label>
                  )
                })}
              </div>
            </div>
          )}
          <label className="space-y-1 text-sm">
            <span>Sucursal</span>
            <select required value={form.branch} onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
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
            <select required value={form.teacher} onChange={(event) => setForm((prev) => ({ ...prev, teacher: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
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
            <select required value={form.class_type} onChange={(event) => setForm((prev) => ({ ...prev, class_type: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
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
            <select required value={form.discipline} onChange={(event) => setForm((prev) => ({ ...prev, discipline: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
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
            <input required type="time" value={form.start_time} onChange={(event) => setForm((prev) => ({ ...prev, start_time: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Hora termino</span>
            <input required type="time" value={form.end_time} onChange={(event) => setForm((prev) => ({ ...prev, end_time: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Capacidad</span>
            <input required min={1} type="number" value={form.capacity} onChange={(event) => setForm((prev) => ({ ...prev, capacity: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          {editingId ? null : (
            <p className="md:col-span-2 text-xs text-brand-muted">
              La clase arranca hoy y no tiene fecha de fin: se genera automaticamente cada semana hacia adelante.
            </p>
          )}
          <label className="space-y-1 text-sm md:col-span-2">
            <span>Descripcion (opcional)</span>
            <textarea value={form.description} onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))} className="min-h-[80px] w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
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
          <div className="md:col-span-2 flex justify-end gap-2">
            {editingId ? (
              <button type="button" onClick={resetForm} className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white">
                Cancelar edicion
              </button>
            ) : null}
            <button type="submit" disabled={saving} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {saving ? 'Guardando...' : editingId ? 'Guardar cambios' : 'Guardar y generar clases'}
            </button>
          </div>
        </form>
        {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
        {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}
      </section>

      <section className="card-surface p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="panel-title">Clases programadas</h2>
          <button
            type="button"
            disabled={!selectedIds.length}
            onClick={() => setBulkModalOpen(true)}
            className="rounded-lg border border-brand-orange px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-50"
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

      <BulkActionModal
        open={bulkModalOpen}
        title="Acciones masivas de clases"
        selectedCount={selectedIds.length}
        loading={bulkWorking}
        actions={[
          { value: 'activate', label: 'Activar clases', description: 'Reanuda la clase para futuras generaciones.' },
          { value: 'deactivate', label: 'Desactivar clases', description: 'Detiene nuevas generaciones sin borrar historico.' },
          { value: 'cancel_future_instances', label: 'Cancelar clases futuras', description: 'Cancela instancias futuras ya generadas.' },
          { value: 'reactivate_future_cancelled', label: 'Reactivar futuras canceladas', description: 'Intenta reactivar futuras canceladas validando seguridad.' },
          { value: 'generate_pending', label: 'Generar rango pendiente', description: 'Genera clases faltantes dentro del rango sin duplicar.' },
          ...(canDeleteSeries
            ? [{ value: 'delete', label: 'Eliminar clases seguras', description: 'Elimina solo clases sin actividad bloqueante.' }]
            : []),
        ]}
        requiresCommentActions={['cancel_future_instances']}
        defaultAction="generate_pending"
        onClose={() => setBulkModalOpen(false)}
        onConfirm={runBulkAction}
      />

      <ConfirmDialog
        open={confirmingAdvance}
        title="Actualizar clases"
        description="Esto va a generar las clases próximas y eliminar las clases vacías vencidas. ¿Continuar?"
        confirmLabel="Sí, actualizar"
        loading={advancingWindows}
        onConfirm={runAdvanceClassWindows}
        onCancel={() => setConfirmingAdvance(false)}
      />
    </div>
  )
}
