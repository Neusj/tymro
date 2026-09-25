import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  compensatePlanMembershipFreezeDays,
  freezePlanMembership,
  getPlanMembershipChangeLog,
  getPlanMembershipFreezeHistory,
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
  payment_method: '',
  reason: '',
}

const freezeInitialForm = {
  start_date: '',
  planned_end_date: '',
  reason: '',
}

const compensationInitialForm = {
  days: 1,
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

function compensationEndDate(currentEndDate, days) {
  const today = todayInput()
  if (!currentEndDate || currentEndDate < today) {
    return addDaysToDate(today, Math.max(days - 1, 0))
  }
  return addDaysToDate(currentEndDate, days)
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

function pluralDays(value) {
  return `${value} ${value === 1 ? 'día' : 'días'}`
}

function auditTitle(log) {
  if (log.field === 'membership_freeze_started') return 'Congelamiento creado'
  if (log.field === 'membership_freeze_completed') return 'Vencimiento ajustado por congelamiento'
  if (log.field === 'membership_freeze_days_compensated') return 'Días compensados por congelamiento'
  return log.field
}

function auditDetail(log) {
  if (log.field === 'membership_freeze_completed') {
    return `Vencimiento de la membresía: ${formatDate(log.old_value)} → ${formatDate(log.new_value)}`
  }
  if (log.field === 'membership_freeze_days_compensated') {
    return `Vencimiento corregido: ${formatDate(log.old_value)} → ${formatDate(log.new_value)}`
  }
  return log.old_value || log.new_value || '-'
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
  const [auditOnly, setAuditOnly] = useState(false)
  const [editForm, setEditForm] = useState(editInitialForm)
  const [freezing, setFreezing] = useState(null)
  const [freezeForm, setFreezeForm] = useState(freezeInitialForm)
  const [unfreezing, setUnfreezing] = useState(null)
  const [changeLog, setChangeLog] = useState([])
  const [changeLogLoading, setChangeLogLoading] = useState(false)
  const [freezeHistory, setFreezeHistory] = useState([])
  const [freezeHistoryLoading, setFreezeHistoryLoading] = useState(false)
  const [compensating, setCompensating] = useState(null)
  const [compensationForm, setCompensationForm] = useState(compensationInitialForm)

  const activeMemberships = useMemo(
    () => memberships.filter(isVisibleAsActive),
    [memberships],
  )

  const historicalMemberships = useMemo(
    () => memberships.filter((membership) => !isVisibleAsActive(membership)),
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

  const openEdit = async (membership, historyOnly = false) => {
    setEditing(membership)
    setAuditOnly(historyOnly)
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
      payment_method: membership.payment_method || '',
      reason: '',
    })
    setChangeLog([])
    setFreezeHistory([])
    setChangeLogLoading(true)
    setFreezeHistoryLoading(true)
    setError('')
    try {
      const [logs, freezes] = await Promise.all([
        getPlanMembershipChangeLog(membership.plan, membership.id),
        getPlanMembershipFreezeHistory(membership.plan, membership.id),
      ])
      setChangeLog(Array.isArray(logs) ? logs : [])
      setFreezeHistory(Array.isArray(freezes) ? freezes : [])
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudo cargar el historial de la membresia.'))
    } finally {
      setChangeLogLoading(false)
      setFreezeHistoryLoading(false)
    }
  }

  const saveMembership = async (event) => {
    event.preventDefault()
    if (!editing || auditOnly) {
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
      if (editing.payment_method_editable) {
        payload.payment_method = editForm.payment_method
      }
      await updatePlanMembership(editing.plan, editing.id, payload)
      setNotice(`Membresia actualizada para ${studentName(student)}.`)
      setEditing(null)
      setChangeLog([])
      setFreezeHistory([])
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
      await unfreezePlanMembership(unfreezing.plan, unfreezing.id, { reason: 'Descongelamiento manual.' })
      setNotice(`Congelamiento finalizado para ${studentName(student)}.`)
      setUnfreezing(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudo liberar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const openCompensation = () => {
    if (!editing) return
    setCompensating(editing)
    setCompensationForm(compensationInitialForm)
    setError('')
  }

  const saveCompensation = async (event) => {
    event.preventDefault()
    if (!compensating || !compensationForm.reason.trim()) {
      setError('Indica por qué se compensan estos días.')
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await compensatePlanMembershipFreezeDays(compensating.plan, compensating.id, {
        days: Number(compensationForm.days),
        reason: compensationForm.reason.trim(),
      })
      setNotice(`${pluralDays(Number(compensationForm.days))} compensado(s) para ${studentName(student)}.`)
      setCompensating(null)
      setEditing(null)
      setFreezeHistory([])
      setChangeLog([])
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError, 'No se pudieron compensar los días por congelamiento.'))
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
                Finalizar congelamiento
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

  // El historial es solo de consulta: una membresía vencida se puede revisar completa,
  // pero las acciones que alteran vigencia, saldo o congelamiento se mantienen reservadas
  // para las membresías vigentes de la sección superior.
  const historicalColumns = useMemo(
    () => [
      ...columns.filter((column) => column.key !== 'actions'),
      {
        key: 'history',
        label: 'Registro',
        sortable: false,
        render: (row, { closeMobileDetail } = {}) => (
          <button
            type="button"
            onClick={() => {
              closeMobileDetail?.()
              openEdit(row, true)
            }}
            className="rounded border border-brand-line px-2 py-1 text-xs text-brand-white"
          >
            Ver historial
          </button>
        ),
      },
    ],
    [columns],
  )

  const freezeDays = daysBetween(freezeForm.start_date, freezeForm.planned_end_date)
  const freezeProjectedEnd = freezing ? addDaysToDate(freezing.end_date, freezeDays) : ''

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={`Membresias - ${studentName(student)}`}
        subtitle="Historial completo de membresias del alumno, con vigencia, saldo y cobros."
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
            <p className="text-xs text-brand-muted">Vencidas o inactivas</p>
            <p className="text-xl font-semibold text-brand-white">{historicalMemberships.length}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Total compradas</p>
            <p className="text-xl font-semibold text-brand-white">{memberships.length}</p>
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

      <section className="card-surface space-y-4 p-5">
        <div>
          <h2 className="text-base font-semibold text-brand-white">Historial de membresias</h2>
          <p className="mt-1 text-sm text-brand-muted">Membresias vencidas, agotadas o dadas de baja. Solo consulta.</p>
        </div>
        {loading ? (
          <div className="space-y-3">
            <div className="h-16 animate-pulse rounded-xl bg-brand-line/40" />
            <div className="h-16 animate-pulse rounded-xl bg-brand-line/30" />
          </div>
        ) : historicalMemberships.length ? (
          <DataTable columns={historicalColumns} data={historicalMemberships} />
        ) : (
          <EmptyState title="Sin membresias historicas" description="Este alumno aun no tiene membresias vencidas o inactivas." />
        )}
      </section>

      <FormModal
        open={Boolean(editing)}
        title={`${auditOnly ? 'Historial de membresia' : 'Editar membresia'}${editing ? ` - ${editing.plan_name || 'Plan'}` : ''}`}
        size="lg"
        closeDisabled={working}
        onClose={() => {
          setEditing(null)
          setChangeLog([])
          setError('')
        }}
      >
        <form onSubmit={saveMembership} className="space-y-5">
          {auditOnly ? (
            <p className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm text-brand-muted">
              Esta membresía es histórica. Sus datos se muestran solo para consulta y auditoría.
            </p>
          ) : null}
          <div className={`grid gap-3 md:grid-cols-2 ${auditOnly ? 'pointer-events-none opacity-60' : ''}`}>
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
            {editing?.payment_method ? (
              <label className="min-w-0 space-y-1 text-sm">
                <span>Tipo de pago</span>
                <select
                  disabled={working || !editing.payment_method_editable}
                  value={editForm.payment_method}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, payment_method: event.target.value }))}
                  className="w-full min-w-0 max-w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 disabled:opacity-60"
                >
                  {editing.payment_method_editable ? (
                    <>
                      <option value="cash">Efectivo</option>
                      <option value="transfer">Transferencia</option>
                      <option value="card">Tarjeta</option>
                      <option value="check">Cheque</option>
                    </>
                  ) : (
                    <option value="mercadopago">Mercado Pago</option>
                  )}
                </select>
                {!editing.payment_method_editable ? (
                  <span className="block text-xs text-brand-muted">Los pagos de Mercado Pago no se pueden modificar.</span>
                ) : null}
              </label>
            ) : null}
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
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-brand-white">Historial de congelamientos</p>
                <p className="text-xs text-brand-muted">Registro inalterable de cada congelamiento de esta membresía.</p>
              </div>
              <p className="text-xs text-brand-muted">{freezeHistory.length} registro(s)</p>
            </div>
            {freezeHistoryLoading ? (
              <p className="mt-3 text-sm text-brand-muted">Cargando congelamientos...</p>
            ) : freezeHistory.length === 0 ? (
              <p className="mt-3 text-sm text-brand-muted">Esta membresía no tiene congelamientos registrados.</p>
            ) : (
              <div className="mt-3 max-h-64 space-y-2 overflow-y-auto pr-1">
                {freezeHistory.map((freeze) => (
                  <article key={freeze.id} className="rounded-lg border border-brand-line bg-brand-panel/60 p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-semibold text-brand-white">
                        {freeze.status === 'active' ? 'Congelamiento abierto' : 'Congelamiento cerrado'}
                      </p>
                      <p className="break-all text-xs text-brand-muted">UUID: {freeze.reference}</p>
                    </div>
                    <p className="mt-1 text-xs text-brand-muted">
                      Período congelado: {formatDate(freeze.start_date)} → {formatDate(freeze.planned_end_date)} ({pluralDays(daysBetween(freeze.start_date, freeze.planned_end_date))})
                    </p>
                    {freeze.actual_end_date ? (
                      <p className="mt-1 text-xs text-brand-muted">
                        La membresía volvió a estar activa el {formatDate(freeze.actual_end_date)}. Se sumó {pluralDays(freeze.extension_days)} al vencimiento.
                      </p>
                    ) : null}
                    <p className="mt-1 text-xs text-brand-muted">
                      Creado por {freeze.created_by_name || 'Sistema'} el {formatAuditDate(freeze.created_at)}
                    </p>
                    {freeze.ended_at ? (
                      <p className="mt-1 text-xs text-brand-muted">
                        Registro cerrado por {freeze.ended_by_name || 'Sistema'} el {formatAuditDate(freeze.ended_at)}.
                      </p>
                    ) : null}
                    {freeze.cancelled_future_enrollments ? (
                      <p className="mt-1 text-xs text-brand-muted">
                        Reservas futuras canceladas: {freeze.cancelled_future_enrollments}
                      </p>
                    ) : null}
                    <p className="mt-2 break-words text-xs text-brand-white">Motivo: {freeze.reason}</p>
                  </article>
                ))}
              </div>
            )}
          </section>

          {auditOnly && freezeHistory.length > 0 ? (
            <section className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-3">
              <p className="text-sm font-semibold text-brand-white">¿El congelamiento dejó días pendientes?</p>
              <p className="mt-1 text-xs text-brand-muted">
                Compensa solo los días que correspondan. Se reactivará la membresía y quedará registrado quién hizo la corrección y por qué.
              </p>
              <button
                type="button"
                disabled={working}
                onClick={openCompensation}
                className="mt-3 min-h-11 w-full rounded-lg border border-amber-400/50 bg-amber-400/10 px-4 py-2 text-sm font-semibold text-amber-100 disabled:opacity-60 sm:w-auto"
              >
                Compensar días por congelamiento
              </button>
            </section>
          ) : null}

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
                      <p className="font-semibold text-brand-white">{auditTitle(log)}</p>
                      <p className="text-xs text-brand-muted">{formatAuditDate(log.created_at)}</p>
                    </div>
                    <p className="mt-1 break-words text-xs text-brand-muted">
                      {auditDetail(log)}
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
                setAuditOnly(false)
                setChangeLog([])
                setFreezeHistory([])
                setError('')
              }}
              className="rounded-lg border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white disabled:opacity-60"
            >
              Cancelar
            </button>
            {!auditOnly ? (
              <button type="submit" disabled={working} className="rounded-lg bg-brand-blue px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
                {working ? 'Guardando...' : 'Guardar cambios'}
              </button>
            ) : null}
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
        title="Finalizar congelamiento"
        description={`Se cerrará el congelamiento de ${studentName(student)}. El vencimiento solo aumentará por el período que la membresía estuvo congelada.`}
        confirmLabel="Finalizar congelamiento"
        loading={working}
        onCancel={() => setUnfreezing(null)}
        onConfirm={unfreezeMembership}
      />

      <FormModal
        open={Boolean(compensating)}
        title="Compensar días por congelamiento"
        size="sm"
        closeDisabled={working}
        onClose={() => {
          setCompensating(null)
          setError('')
        }}
      >
        <form onSubmit={saveCompensation} className="space-y-5">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3 text-sm">
            <p className="text-xs text-brand-muted">Vencimiento actual</p>
            <p className="mt-1 font-semibold text-brand-white">{formatDate(compensating?.end_date)}</p>
          </div>
          <label className="block space-y-1 text-sm">
            <span className="font-semibold">Días a compensar</span>
            <input
              required
              type="number"
              min="1"
              max="366"
              inputMode="numeric"
              disabled={working}
              value={compensationForm.days}
              onChange={(event) => setCompensationForm((prev) => ({ ...prev, days: event.target.value }))}
              className="min-h-12 w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-base"
            />
          </label>
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">
            <p className="text-xs text-brand-muted">Nuevo vencimiento</p>
            <p className="mt-1 font-semibold text-brand-white">
              {formatDate(compensationEndDate(compensating?.end_date, Number(compensationForm.days) || 0))}
            </p>
            <p className="mt-1 text-xs text-brand-muted">Si ya venció, los días se cuentan desde hoy, incluyendo hoy como el primer día.</p>
          </div>
          <label className="block space-y-1 text-sm">
            <span className="font-semibold">Motivo de la corrección</span>
            <textarea
              required
              rows={3}
              disabled={working}
              value={compensationForm.reason}
              onChange={(event) => setCompensationForm((prev) => ({ ...prev, reason: event.target.value }))}
              placeholder="Ej.: congelamiento registrado con una duración incorrecta"
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" disabled={working} onClick={() => setCompensating(null)} className="min-h-11 rounded-lg border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white disabled:opacity-60">Cancelar</button>
            <button type="submit" disabled={working || Number(compensationForm.days) < 1} className="min-h-11 rounded-lg bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {working ? 'Guardando...' : 'Confirmar compensación'}
            </button>
          </div>
        </form>
      </FormModal>
    </div>
  )
}
