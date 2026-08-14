import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getPlanById, getPlanMembershipChangeLog, getPlanMemberships, removePlanMembership, updatePlanMembership } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import { formatDate } from '../utils/format'

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

function asDateInput(value) {
  return value ? String(value).slice(0, 10) : ''
}

function asDateTimeInput(value) {
  if (!value) {
    return ''
  }
  return String(value).slice(0, 16)
}

function asDateTimePayload(value) {
  if (!value) {
    return null
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  return date.toISOString()
}

function formatAuditDate(value) {
  if (!value) {
    return '-'
  }
  try {
    return new Date(value).toLocaleString('es-CL', {
      dateStyle: 'short',
      timeStyle: 'short',
    })
  } catch {
    return String(value)
  }
}

const editInitialForm = {
  start_date: '',
  end_date: '',
  total_classes: '',
  unlimited_classes: false,
  classes_used: '',
  discount_percentage: '',
  final_price: '',
  enrollment_fee: '',
  enrollment_fee_paid_at: '',
  enrollment_fee_due_at: '',
  is_active: true,
  reason: '',
}

export default function GymAdminPlanMembershipsPage() {
  const { id } = useParams()
  const [plan, setPlan] = useState(null)
  const [memberships, setMemberships] = useState([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [deleting, setDeleting] = useState(null)
  const [filter, setFilter] = useState('active')
  const [editing, setEditing] = useState(null)
  const [editForm, setEditForm] = useState(editInitialForm)
  const [changeLog, setChangeLog] = useState([])
  const [changeLogLoading, setChangeLogLoading] = useState(false)

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [planData, membershipsData] = await Promise.all([getPlanById(id), getPlanMemberships(id)])
      setPlan(planData)
      setMemberships(Array.isArray(membershipsData) ? membershipsData : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las membresias del plan.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  // Se cuenta el MISMO estado que pinta la columna, no `is_active`. El flag significa "no
  // fue reemplazada" y `activate_student_plan` lo deja en true para siempre, así que el
  // KPI decía "12 activas" sobre una tabla de 12 filas que decían "Vencido". El endpoint
  // sigue devolviendo el histórico completo: lo que cambia es qué se cuenta de él.
  const activeCount = useMemo(
    () => memberships.filter((item) => item.validity_status === 'active').length,
    [memberships],
  )
  const displayedMemberships = useMemo(
    () => (filter === 'active' ? memberships.filter((item) => item.validity_status === 'active') : memberships),
    [filter, memberships],
  )

  const removeMembership = async () => {
    if (!deleting) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await removePlanMembership(id, deleting.id)
      setNotice(`Membresia quitada para ${deleting.user_name || deleting.user_email || 'alumno'}.`)
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo quitar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const openEdit = async (membership) => {
    setEditing(membership)
    setEditForm({
      start_date: asDateInput(membership.start_date),
      end_date: asDateInput(membership.end_date),
      total_classes: membership.total_classes ?? '',
      unlimited_classes: Boolean(membership.unlimited_classes),
      classes_used: membership.classes_used ?? 0,
      discount_percentage: membership.discount_percentage ?? 0,
      final_price: membership.final_price ?? 0,
      enrollment_fee: membership.enrollment_fee ?? 0,
      enrollment_fee_paid_at: asDateTimeInput(membership.enrollment_fee_paid_at),
      enrollment_fee_due_at: asDateInput(membership.enrollment_fee_due_at),
      is_active: Boolean(membership.is_active),
      reason: '',
    })
    setChangeLog([])
    setChangeLogLoading(true)
    try {
      const logs = await getPlanMembershipChangeLog(id, membership.id)
      setChangeLog(Array.isArray(logs) ? logs : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la auditoría de la membresía.'))
    } finally {
      setChangeLogLoading(false)
    }
  }

  const saveMembership = async (event) => {
    event.preventDefault()
    if (!editing) {
      return
    }
    if (!editForm.reason.trim()) {
      setError('Indica el motivo del cambio de membresía.')
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      const payload = {
        start_date: editForm.start_date,
        end_date: editForm.end_date,
        total_classes: Number(editForm.total_classes || 0),
        unlimited_classes: Boolean(editForm.unlimited_classes),
        classes_used: Number(editForm.classes_used || 0),
        discount_percentage: Number(editForm.discount_percentage || 0),
        final_price: Number(editForm.final_price || 0),
        enrollment_fee: String(editForm.enrollment_fee || 0),
        enrollment_fee_paid_at: asDateTimePayload(editForm.enrollment_fee_paid_at),
        enrollment_fee_due_at: editForm.enrollment_fee_due_at || null,
        is_active: Boolean(editForm.is_active),
        reason: editForm.reason.trim(),
      }
      await updatePlanMembership(id, editing.id, payload)
      setNotice(`Membresía actualizada para ${editing.user_name || editing.user_email || 'alumno'}.`)
      setEditing(null)
      setChangeLog([])
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo actualizar la membresía.'))
    } finally {
      setWorking(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'user_name', label: 'Alumno', render: (row) => row.user_name || `#${row.user}` },
      { key: 'user_email', label: 'Email', render: (row) => row.user_email || '-' },
      { key: 'start_date', label: 'Inicio', render: (row) => formatDate(row.start_date) },
      { key: 'end_date', label: 'Termino', render: (row) => formatDate(row.end_date) },
      { key: 'total_classes', label: 'Clases totales', render: (row) => (row.unlimited_classes ? 'Ilimitadas' : row.total_classes) },
      { key: 'classes_used', label: 'Usadas' },
      { key: 'remaining_classes', label: 'Disponibles' },
      {
        key: 'validity_status',
        label: 'Estado',
        // La escalera de cuatro ramas mandaba al `else` ("Inactiva") todo lo que no
        // conocía, o sea exactamente los dos estados que 7.3 destapa.
        //
        // Sigue siendo un chip y no texto pelado: en móvil DataTable manda esta celda a la
        // zona `meta`, que NO aporta estilo propio, así que el color tiene que venir del
        // contenido. La severidad la decide el backend; acá no se deriva nada.
        render: (row) => <PlanAlertBadge level={row.expiry_alert_level} message={row.validity_status_label} />,
      },
      {
        key: 'alert',
        label: 'Alerta',
        sortable: false,
        render: (row) => <PlanAlertBadge level={row.expiry_alert_level} message={row.expiry_alert_message} />,
      },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={working}
              onClick={() => openEdit(row)}
              className="rounded border border-brand-line px-2 py-1 text-xs text-brand-white disabled:opacity-50"
            >
              Editar
            </button>
            <button
              type="button"
              disabled={working || Number(row.classes_used || 0) > 0}
              onClick={() => setDeleting(row)}
              className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200 disabled:opacity-50"
              title={Number(row.classes_used || 0) > 0 ? 'No se puede quitar si ya utilizó clases.' : ''}
            >
              Quitar plan
            </button>
          </div>
        ),
        mobilePrimary: (row) => (
          <button
            type="button"
            disabled={working}
            onClick={() => openEdit(row)}
            className="rounded-lg border border-brand-blue/50 bg-brand-blue/10 px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-50"
          >
            Editar membresia
          </button>
        ),
      },
    ],
    [working],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={`Membresias · ${plan?.name || 'Plan'}`}
        subtitle="Revisa membresias activas, edita sus saldos y conserva trazabilidad de cada cambio."
        back={{ to: '/gym-admin/plans', label: 'Planes' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Total membresias</p>
            <p className="text-xl font-semibold">{memberships.length}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Membresias activas</p>
            <p className="text-xl font-semibold">{activeCount}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Politica actual</p>
            <p className="text-sm font-semibold">Edicion auditada</p>
          </div>
        </div>
      </section>

      <section className="card-surface space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-brand-white">Membresias</p>
            <p className="text-xs text-brand-muted">
              {filter === 'active' ? 'Mostrando solo membresias vigentes.' : 'Mostrando el historico completo.'}
            </p>
          </div>
          <div className="inline-flex rounded-lg border border-brand-line bg-black/20 p-1">
            <button
              type="button"
              onClick={() => setFilter('active')}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${filter === 'active' ? 'bg-brand-blue text-white' : 'text-brand-muted'}`}
            >
              Activas
            </button>
            <button
              type="button"
              onClick={() => setFilter('all')}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${filter === 'all' ? 'bg-brand-blue text-white' : 'text-brand-muted'}`}
            >
              Todas
            </button>
          </div>
        </div>
        <DataTable columns={columns} data={displayedMemberships} loading={loading} />
      </section>

      <FormModal
        open={Boolean(editing)}
        title={`Editar membresia${editing ? ` · ${editing.user_name || editing.user_email || 'Alumno'}` : ''}`}
        size="lg"
        closeDisabled={working}
        onClose={() => {
          setEditing(null)
          setChangeLog([])
          setError('')
        }}
      >
        <form onSubmit={saveMembership} className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="min-w-0 space-y-1 text-sm">
              <span>Fecha inicio</span>
              <input
                required
                type="date"
                disabled={working}
                value={editForm.start_date}
                onChange={(event) => setEditForm((prev) => ({ ...prev, start_date: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Fecha termino</span>
              <input
                required
                type="date"
                disabled={working}
                value={editForm.end_date}
                onChange={(event) => setEditForm((prev) => ({ ...prev, end_date: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm">
              <input
                type="checkbox"
                disabled={working}
                checked={editForm.unlimited_classes}
                onChange={(event) => setEditForm((prev) => ({ ...prev, unlimited_classes: event.target.checked }))}
                className="h-4 w-4 accent-brand-blue"
              />
              <span>Clases ilimitadas</span>
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Clases totales</span>
              <input
                type="number"
                min="0"
                step="1"
                disabled={working || editForm.unlimited_classes}
                value={editForm.total_classes}
                onChange={(event) => setEditForm((prev) => ({ ...prev, total_classes: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 disabled:opacity-60"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Asistencias usadas</span>
              <input
                required
                type="number"
                min="0"
                step="1"
                disabled={working}
                value={editForm.classes_used}
                onChange={(event) => setEditForm((prev) => ({ ...prev, classes_used: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Descuento %</span>
              <input
                type="number"
                min="0"
                max="100"
                step="0.01"
                disabled={working}
                value={editForm.discount_percentage}
                onChange={(event) => setEditForm((prev) => ({ ...prev, discount_percentage: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Precio final</span>
              <input
                type="number"
                min="0"
                step="0.01"
                disabled={working}
                value={editForm.final_price}
                onChange={(event) => setEditForm((prev) => ({ ...prev, final_price: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Matricula</span>
              <input
                type="number"
                min="0"
                step="0.01"
                disabled={working}
                value={editForm.enrollment_fee}
                onChange={(event) => setEditForm((prev) => ({ ...prev, enrollment_fee: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Matricula pagada</span>
              <input
                type="datetime-local"
                disabled={working}
                value={editForm.enrollment_fee_paid_at}
                onChange={(event) => setEditForm((prev) => ({ ...prev, enrollment_fee_paid_at: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Vence matricula</span>
              <input
                type="date"
                disabled={working}
                value={editForm.enrollment_fee_due_at}
                onChange={(event) => setEditForm((prev) => ({ ...prev, enrollment_fee_due_at: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm">
              <input
                type="checkbox"
                disabled={working}
                checked={editForm.is_active}
                onChange={(event) => setEditForm((prev) => ({ ...prev, is_active: event.target.checked }))}
                className="h-4 w-4 accent-brand-blue"
              />
              <span>Membresia activa</span>
            </label>
            <label className="min-w-0 space-y-1 text-sm md:col-span-2">
              <span>Motivo del cambio</span>
              <textarea
                required
                rows={3}
                disabled={working}
                value={editForm.reason}
                onChange={(event) => setEditForm((prev) => ({ ...prev, reason: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
          </div>

          <section className="rounded-xl border border-brand-line bg-black/20 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold text-brand-white">Auditoria</p>
              <p className="text-xs text-brand-muted">{changeLog.length} cambios</p>
            </div>
            {changeLogLoading ? (
              <p className="mt-3 text-sm text-brand-muted">Cargando auditoria...</p>
            ) : changeLog.length === 0 ? (
              <p className="mt-3 text-sm text-brand-muted">Sin cambios auditados todavia.</p>
            ) : (
              <div className="mt-3 max-h-56 space-y-2 overflow-y-auto pr-1">
                {changeLog.map((log) => (
                  <article key={log.id} className="rounded-lg border border-brand-line bg-brand-panel/60 p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-semibold text-brand-white">{log.field}</p>
                      <p className="text-xs text-brand-muted">{formatAuditDate(log.created_at)}</p>
                    </div>
                    <p className="mt-1 break-words text-xs text-brand-muted">
                      {log.old_value || '-'} -&gt; {log.new_value || '-'}
                    </p>
                    <p className="mt-1 text-xs text-brand-muted">{log.changed_by_name || 'Sistema'}</p>
                    {log.reason ? <p className="mt-2 break-words text-xs text-brand-white">{log.reason}</p> : null}
                  </article>
                ))}
              </div>
            )}
          </section>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={working}
              onClick={() => {
                setEditing(null)
                setChangeLog([])
                setError('')
              }}
              className="rounded-lg border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white disabled:opacity-60"
            >
              Cancelar
            </button>
            <button type="submit" disabled={working} className="rounded-lg bg-brand-blue px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {working ? 'Guardando...' : 'Guardar cambios'}
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Quitar membresia"
        description={`Se quitara el plan de ${deleting?.user_name || deleting?.user_email || 'este alumno'}. Solo permitido si no ha usado clases.`}
        confirmLabel="Quitar plan"
        loading={working}
        onCancel={() => setDeleting(null)}
        onConfirm={removeMembership}
      />
    </div>
  )
}
