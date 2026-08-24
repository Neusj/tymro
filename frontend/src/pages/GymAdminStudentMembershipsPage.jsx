import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  freezePlanMembership,
  getPlanMembershipChangeLog,
  getStudentOverview,
  unfreezePlanMembership,
  updatePlanMembership,
} from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import { extractApiErrorMessage } from '../utils/apiErrors'
import { formatDate } from '../utils/format'

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

const freezeInitialForm = {
  start_date: '',
  planned_end_date: '',
  reason: '',
}

function asDateInput(value) {
  return value ? String(value).slice(0, 10) : ''
}

function todayInput() {
  return new Date().toISOString().slice(0, 10)
}

function addDaysInput(value, days) {
  const base = value ? new Date(`${value}T00:00:00`) : new Date()
  base.setDate(base.getDate() + days)
  return base.toISOString().slice(0, 10)
}

function daysBetween(startDate, endDate) {
  if (!startDate || !endDate) {
    return 0
  }
  const start = new Date(`${startDate}T00:00:00`)
  const end = new Date(`${endDate}T00:00:00`)
  const diff = Math.round((end.getTime() - start.getTime()) / 86400000)
  return Math.max(diff, 0)
}

function addDaysToDate(value, days) {
  if (!value) {
    return ''
  }
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

function asDateTimeInput(value) {
  return value ? String(value).slice(0, 16) : ''
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

function firstApiError(apiError, fallback) {
  return extractApiErrorMessage(apiError, fallback)
}

function studentName(student) {
  return student?.name || student?.email || 'Alumno'
}

function hasOpenFreeze(membership) {
  return Boolean(membership?.active_freeze)
}

function displayStatusLabel(membership) {
  return hasOpenFreeze(membership) ? 'Congelada' : membership.validity_status_label
}

function displayStatusLevel(membership) {
  return hasOpenFreeze(membership) ? 'warning' : membership.expiry_alert_level
}

function isVisibleAsActive(membership) {
  return hasOpenFreeze(membership) || ['active', 'frozen'].includes(membership.validity_status)
}

export default function GymAdminStudentMembershipsPage() {
  const { studentId } = useParams()
  const [student, setStudent] = useState(null)
  const [memberships, setMemberships] = useState([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(null)
  const [editForm, setEditForm] = useState(editInitialForm)
  const [freezing, setFreezing] = useState(null)
  const [freezeForm, setFreezeForm] = useState(freezeInitialForm)
  const [unfreezing, setUnfreezing] = useState(null)
  const [changeLog, setChangeLog] = useState([])
  const [changeLogLoading, setChangeLogLoading] = useState(false)

  const activeMemberships = useMemo(
    () => memberships.filter(isVisibleAsActive),
    [memberships],
  )

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getStudentOverview(studentId)
      setStudent(data.student || null)
      setMemberships(Array.isArray(data.memberships) ? data.memberships : [])
    } catch (apiError) {
      setStudent(null)
      setMemberships([])
      setError(firstApiError(apiError, 'No se pudieron cargar las membresias del alumno.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [studentId])

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
    setError('')
    try {
      const logs = await getPlanMembershipChangeLog(membership.plan, membership.id)
      setChangeLog(Array.isArray(logs) ? logs : [])
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudo cargar la auditoria de la membresia.'))
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
      setError('Indica el motivo del cambio de membresia.')
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
      await updatePlanMembership(editing.plan, editing.id, payload)
      setNotice(`Membresia actualizada para ${studentName(student)}.`)
      setEditing(null)
      setChangeLog([])
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudo actualizar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const openFreeze = (membership) => {
    const start = todayInput()
    setFreezing(membership)
    setFreezeForm({
      start_date: start,
      planned_end_date: addDaysInput(start, 1),
      reason: '',
    })
    setError('')
    setNotice('')
  }

  const saveFreeze = async (event) => {
    event.preventDefault()
    if (!freezing) {
      return
    }
    if (!freezeForm.reason.trim()) {
      setError('Indica el motivo del congelamiento.')
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await freezePlanMembership(freezing.plan, freezing.id, {
        start_date: freezeForm.start_date,
        planned_end_date: freezeForm.planned_end_date,
        reason: freezeForm.reason.trim(),
      })
      setNotice(`Membresia congelada para ${studentName(student)}.`)
      setFreezing(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudo congelar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const unfreezeMembership = async () => {
    if (!unfreezing) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await unfreezePlanMembership(unfreezing.plan, unfreezing.id, { reason: 'Liberacion anticipada.' })
      setNotice(`Membresia liberada para ${studentName(student)}.`)
      setUnfreezing(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudo liberar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'plan_name', label: 'Plan', mobile: 'title', render: (row) => row.plan_name || 'Plan' },
      { key: 'start_date', label: 'Inicio', mobile: 'secondary', render: (row) => formatDate(row.start_date) },
      { key: 'end_date', label: 'Termino', mobile: 'secondary', render: (row) => formatDate(row.end_date) },
      { key: 'total_classes', label: 'Clases totales', render: (row) => (row.unlimited_classes ? 'Ilimitadas' : row.total_classes) },
      { key: 'classes_used', label: 'Usadas' },
      { key: 'remaining_classes', label: 'Disponibles', render: (row) => (row.unlimited_classes ? 'Ilimitadas' : row.remaining_classes) },
      {
        key: 'validity_status',
        label: 'Estado',
        mobile: 'meta',
        render: (row) => <PlanAlertBadge level={displayStatusLevel(row)} message={displayStatusLabel(row)} />,
      },
      {
        key: 'freeze',
        label: 'Congelamiento',
        sortable: false,
        render: (row) => {
          const freeze = row.active_freeze
          if (!freeze) {
            return '-'
          }
          return (
            <div className="space-y-1 text-xs">
              <p className="font-semibold text-brand-white">
                {formatDate(freeze.start_date)} - {formatDate(freeze.planned_end_date)}
              </p>
              <p className="text-brand-muted">Vence: {formatDate(freeze.projected_end_date)}</p>
            </div>
          )
        },
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
            {row.active_freeze ? (
              <button
                type="button"
                disabled={working}
                onClick={() => setUnfreezing(row)}
                className="rounded border border-amber-400/50 px-2 py-1 text-xs text-amber-100 disabled:opacity-50"
              >
                Liberar
              </button>
            ) : (
              <button
                type="button"
                disabled={working}
                onClick={() => openFreeze(row)}
                className="rounded border border-brand-line px-2 py-1 text-xs text-brand-white disabled:opacity-50"
              >
                Congelar
              </button>
            )}
          </div>
        ),
        mobilePrimaryReplacesDetail: true,
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

  const freezeDays = daysBetween(freezeForm.start_date, freezeForm.planned_end_date)
  const freezeProjectedEnd = freezing ? addDaysToDate(freezing.end_date, freezeDays) : ''

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={`Membresias - ${studentName(student)}`}
        subtitle="Membresias activas del alumno, con edicion auditada de vigencia, saldo y cobros."
        back={{ to: '/gym-admin/users', label: 'Usuarios' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Alumno</p>
            <p className="truncate text-sm font-semibold text-brand-white">{studentName(student)}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Membresias activas</p>
            <p className="text-xl font-semibold text-brand-white">{activeMemberships.length}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Trazabilidad</p>
            <p className="text-sm font-semibold text-brand-white">Edicion auditada</p>
          </div>
        </div>
      </section>

      <section className="card-surface space-y-4 p-5">
        {loading ? (
          <div className="space-y-3">
            <div className="h-16 animate-pulse rounded-xl bg-brand-line/40" />
            <div className="h-16 animate-pulse rounded-xl bg-brand-line/30" />
          </div>
        ) : activeMemberships.length ? (
          <DataTable columns={columns} data={activeMemberships} />
        ) : (
          <EmptyState title="Sin membresias activas" description="Este alumno no tiene planes vigentes para modificar." />
        )}
      </section>

      <FormModal
        open={Boolean(editing)}
        title={`Editar membresia${editing ? ` - ${editing.plan_name || 'Plan'}` : ''}`}
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

      <FormModal
        open={Boolean(freezing)}
        title={`Congelar membresia${freezing ? ` - ${freezing.plan_name || 'Plan'}` : ''}`}
        size="md"
        closeDisabled={working}
        onClose={() => {
          setFreezing(null)
          setError('')
        }}
      >
        <form onSubmit={saveFreeze} className="space-y-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="min-w-0 space-y-1 text-sm">
              <span>Inicio</span>
              <input
                required
                type="date"
                disabled={working}
                value={freezeForm.start_date}
                onChange={(event) => {
                  const nextStart = event.target.value
                  setFreezeForm((prev) => ({
                    ...prev,
                    start_date: nextStart,
                    planned_end_date: prev.planned_end_date && prev.planned_end_date > nextStart
                      ? prev.planned_end_date
                      : addDaysInput(nextStart, 1),
                  }))
                }}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm">
              <span>Termino</span>
              <input
                required
                type="date"
                disabled={working}
                value={freezeForm.planned_end_date}
                onChange={(event) => setFreezeForm((prev) => ({ ...prev, planned_end_date: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
            <label className="min-w-0 space-y-1 text-sm md:col-span-2">
              <span>Motivo</span>
              <textarea
                required
                rows={3}
                disabled={working}
                value={freezeForm.reason}
                onChange={(event) => setFreezeForm((prev) => ({ ...prev, reason: event.target.value }))}
                className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>
          </div>

          <div className="rounded-lg border border-brand-line bg-black/20 p-3 text-sm">
            Esta membresia se congelara por {freezeDays} dia(s) y su vencimiento se extendera en {freezeDays} dia(s).
            {freezeProjectedEnd ? <span className="block text-brand-muted">Nuevo vencimiento previsto: {formatDate(freezeProjectedEnd)}</span> : null}
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={working}
              onClick={() => {
                setFreezing(null)
                setError('')
              }}
              className="rounded-lg border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white disabled:opacity-60"
            >
              Cancelar
            </button>
            <button type="submit" disabled={working || freezeDays <= 0} className="rounded-lg bg-brand-blue px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {working ? 'Guardando...' : 'Congelar membresia'}
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(unfreezing)}
        title="Liberar membresia"
        description={`Se cerrara el congelamiento de ${studentName(student)} y se extendera el vencimiento solo por los dias realmente congelados.`}
        confirmLabel="Liberar"
        loading={working}
        onCancel={() => setUnfreezing(null)}
        onConfirm={unfreezeMembership}
      />
    </div>
  )
}
