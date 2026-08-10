import { useEffect, useMemo, useState } from 'react'
import { organizationsApi, teacherPaymentRulesApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { canManageAdmin } from '../utils/roles'

const EMPTY_FORM = {
  organization: '',
  payment_type: 'fixed_per_class',
  amount: '',
  calculation_base: '',
  per_plan_price_base: '',
  is_active: true,
}

const PCT_TYPES = ['revenue_share', 'per_plan_price']

const AMOUNT_LABELS = {
  fixed_per_class: 'Monto por clase',
  per_student: 'Monto por alumno presente',
  per_enrolled: 'Monto por alumno inscrito',
  per_hour: 'Valor por hora',
  revenue_share: 'Porcentaje (%)',
  per_plan_price: 'Porcentaje (%)',
  monthly_fixed: 'Sueldo mensual',
}

const AMOUNT_HINTS = {
  per_hour: 'Se multiplica por la duracion de cada clase.',
  per_enrolled: 'Se multiplica por los alumnos inscritos activos al cerrar la clase.',
  monthly_fixed: 'Monto completo por cada mes del periodo. No genera pago por clase.',
  per_plan_price: '% del precio por clase del plan de cada alumno (precio / clases del plan).',
}

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

function buildRulePayload(form) {
  const payload = {
    payment_type: form.payment_type,
    amount: Number(form.amount),
    calculation_base: form.payment_type === 'revenue_share' ? form.calculation_base : null,
    is_active: Boolean(form.is_active),
  }

  if (form.payment_type === 'per_plan_price') {
    payload.per_plan_price_base = form.per_plan_price_base
  }

  return payload
}

export default function TeacherPaymentRulesPage() {
  const { user } = useAuth()
  const isSuperadmin = user?.role === 'superadmin'
  const canManage = canManageAdmin(user?.role)

  const [rules, setRules] = useState([])
  const [organizations, setOrganizations] = useState([])
  const [selectedOrganizationId, setSelectedOrganizationId] = useState(user?.organization ? String(user.organization) : '')
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [assignmentsOpen, setAssignmentsOpen] = useState(false)
  const [assignmentsRule, setAssignmentsRule] = useState(null)
  const [assignmentItems, setAssignmentItems] = useState([])
  const [assignmentSelectedIds, setAssignmentSelectedIds] = useState([])
  const [deletingRule, setDeletingRule] = useState(null)

  const clearForm = () => {
    setEditing(null)
    setForm({
      ...EMPTY_FORM,
      organization: selectedOrganizationId || '',
    })
  }

  const loadOrganizations = async () => {
    if (!isSuperadmin) {
      return
    }
    try {
      const data = await organizationsApi.list()
      const list = Array.isArray(data) ? data : []
      setOrganizations(list)
      if (!selectedOrganizationId && list.length > 0) {
        setSelectedOrganizationId(String(list[0].id))
      }
    } catch {
      setOrganizations([])
    }
  }

  const loadData = async () => {
    setLoading(true)
    setError('')

    if (isSuperadmin && !selectedOrganizationId) {
      setRules([])
      setLoading(false)
      return
    }

    try {
      const baseParams = {}
      if (isSuperadmin) {
        baseParams.organization_id = selectedOrganizationId
      }

      const rulesData = await teacherPaymentRulesApi.list({ ...baseParams, ordering: '-updated_at' })
      setRules(Array.isArray(rulesData) ? rulesData : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar reglas de pago.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOrganizations()
  }, [isSuperadmin])

  useEffect(() => {
    loadData()
  }, [isSuperadmin, selectedOrganizationId])

  const openCreate = () => {
    clearForm()
    setFormOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    setForm({
      organization: row.organization ? String(row.organization) : selectedOrganizationId || '',
      payment_type: row.payment_type || 'fixed_per_class',
      amount: row.amount ?? '',
      calculation_base: row.calculation_base || '',
      per_plan_price_base: row.per_plan_price_base || '',
      is_active: Boolean(row.is_active),
    })
    setFormOpen(true)
  }

  const openAssignments = async (row) => {
    setError('')
    setAssignmentsRule(row)
    setAssignmentsOpen(true)
    setWorking(true)
    try {
      const data = await teacherPaymentRulesApi.assignments(row.id)
      const list = Array.isArray(data) ? data : []
      setAssignmentItems(list)
      setAssignmentSelectedIds(list.filter((item) => item.is_assigned).map((item) => item.teacher_id))
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar asignaciones.'))
      setAssignmentsOpen(false)
    } finally {
      setWorking(false)
    }
  }

  const saveAssignments = async (event) => {
    event.preventDefault()
    if (!assignmentsRule?.id) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await teacherPaymentRulesApi.updateAssignments(assignmentsRule.id, assignmentSelectedIds)
      setNotice('Asignaciones actualizadas.')
      setAssignmentsOpen(false)
      setAssignmentsRule(null)
      setAssignmentItems([])
      setAssignmentSelectedIds([])
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron guardar las asignaciones.'))
    } finally {
      setWorking(false)
    }
  }

  const handleDisable = async (row) => {
    if (!row?.id) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await teacherPaymentRulesApi.update(row.id, {
        ...buildRulePayload({
          payment_type: row.payment_type,
          amount: row.amount,
          calculation_base: row.calculation_base || '',
          per_plan_price_base: row.per_plan_price_base || '',
          is_active: false,
        }),
        ...(isSuperadmin ? { organization: row.organization } : {}),
      })
      setNotice('Regla deshabilitada.')
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo deshabilitar la regla.'))
    } finally {
      setWorking(false)
    }
  }

  const handleDelete = async () => {
    if (!deletingRule?.id) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await teacherPaymentRulesApi.remove(deletingRule.id)
      setNotice('Regla eliminada.')
      setDeletingRule(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo eliminar la regla.'))
    } finally {
      setWorking(false)
    }
  }

  const submitForm = async (event) => {
    event.preventDefault()

    if (isSuperadmin && !form.organization) {
      setError('Debes seleccionar organizacion.')
      return
    }
    if (form.amount === '' || Number(form.amount) < 0) {
      setError('Debes ingresar un monto valido.')
      return
    }
    if (form.payment_type === 'revenue_share' && !form.calculation_base) {
      setError('Debes seleccionar base de calculo para porcentaje.')
      return
    }
    if (form.payment_type === 'per_plan_price' && !form.per_plan_price_base) {
      setError('Debes seleccionar si el porcentaje es por asistencia o por reserva.')
      return
    }

    setWorking(true)
    setError('')
    setNotice('')
    try {
      const payload = buildRulePayload(form)
      if (isSuperadmin) {
        payload.organization = Number(form.organization)
      }
      if (editing) {
        await teacherPaymentRulesApi.update(editing.id, payload)
        setNotice('Regla actualizada.')
      } else {
        await teacherPaymentRulesApi.create(payload)
        setNotice('Regla creada.')
      }
      setFormOpen(false)
      clearForm()
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo guardar la regla.'))
    } finally {
      setWorking(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'payment_type', label: 'Tipo', render: (row) => <ValueBadge kind="payment_type" value={row.payment_type} /> },
      { key: 'amount', label: 'Monto', render: (row) => (PCT_TYPES.includes(row.payment_type) ? `${Number(row.amount || 0).toLocaleString('es-CL')}%` : `$${Number(row.amount || 0).toLocaleString('es-CL')}`) },
      { key: 'calculation_base', label: 'Base', render: (row) => row.per_plan_price_base || row.calculation_base || '-' },
      { key: 'usage_count', label: 'Asignaciones' },
      { key: 'assigned_teachers_count', label: 'Profesores asignados' },
      { key: 'is_active', label: 'Estado', render: (row) => <ValueBadge kind="template_status" value={row.is_active ? 'active' : 'inactive'} /> },
      ...(canManage
        ? [{
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={working}
              onClick={() => openAssignments(row)}
              className="rounded border border-brand-line px-2 py-1 text-xs text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
            >
              Ver asignaciones
            </button>
            <button
              type="button"
              disabled={working || row.is_used}
              onClick={() => openEdit(row)}
              className="rounded border border-brand-line px-2 py-1 text-xs text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
              title={row.is_used ? 'No editable porque ya tiene pagos calculados.' : ''}
            >
              Editar
            </button>
            {row.is_used ? (
              <button
                type="button"
                disabled={working || !row.is_active}
                onClick={() => handleDisable(row)}
                className="rounded border border-amber-500/40 px-2 py-1 text-xs text-amber-200 transition disabled:cursor-not-allowed disabled:opacity-50"
              >
                Deshabilitar
              </button>
            ) : (
              <button
                type="button"
                disabled={working}
                onClick={() => setDeletingRule(row)}
                className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200 transition disabled:cursor-not-allowed disabled:opacity-50"
              >
                Eliminar
              </button>
            )}
          </div>
        ),
      }]
        : []),
    ],
    [working, canManage],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Pagos Profesores - Reglas"
        subtitle="Configura reglas por profesor para calcular pagos al cerrar clase."
        extra={
          canManage ? (
            <button type="button" onClick={openCreate} className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-black transition hover:brightness-110">
              Nueva regla
            </button>
          ) : null
        }
      />

      {isSuperadmin ? (
        <section className="card-surface p-5">
          <label className="space-y-1 text-sm">
            <span className="text-brand-muted">Organizacion</span>
            <select
              value={selectedOrganizationId}
              onChange={(event) => setSelectedOrganizationId(event.target.value)}
              className="w-full max-w-md rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar</option>
              {organizations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        </section>
      ) : null}

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      <section className="card-surface p-5">
        <DataTable columns={columns} data={rules} loading={loading} defaultSort={{ key: 'updated_at', direction: 'desc' }} />
      </section>

      <FormModal
        open={formOpen}
        title={editing ? 'Editar regla de pago' : 'Nueva regla de pago'}
        closeDisabled={working}
        onClose={() => {
          setFormOpen(false)
          clearForm()
        }}
      >
        <form onSubmit={submitForm} className="space-y-3">
          {isSuperadmin ? (
            <label className="space-y-1 text-sm">
              <span className="text-brand-muted">Organizacion</span>
              <select
                value={form.organization}
                onChange={(event) => setForm((prev) => ({ ...prev, organization: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              >
                <option value="">Seleccionar</option>
                {organizations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label className="space-y-1 text-sm">
            <span className="text-brand-muted">Tipo de pago</span>
            <select
              value={form.payment_type}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  payment_type: event.target.value,
                  calculation_base: event.target.value === 'revenue_share' ? prev.calculation_base : '',
                  per_plan_price_base: event.target.value === 'per_plan_price' ? prev.per_plan_price_base : '',
                }))
              }
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="fixed_per_class">Fijo por clase</option>
              <option value="per_student">Por alumno presente</option>
              <option value="per_enrolled">Por alumno inscrito</option>
              <option value="per_hour">Por hora</option>
              <option value="per_plan_price">% del precio del plan</option>
              <option value="monthly_fixed">Sueldo mensual fijo</option>
            </select>
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-brand-muted">{AMOUNT_LABELS[form.payment_type] || 'Monto'}</span>
            <input
              type="number"
              min={0}
              value={form.amount}
              onChange={(event) => setForm((prev) => ({ ...prev, amount: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
            {AMOUNT_HINTS[form.payment_type] ? (
              <span className="block text-xs text-brand-muted">{AMOUNT_HINTS[form.payment_type]}</span>
            ) : null}
          </label>

          {form.payment_type === 'revenue_share' ? (
            <label className="space-y-1 text-sm">
              <span className="text-brand-muted">Base de calculo</span>
              <select
                value={form.calculation_base}
                onChange={(event) => setForm((prev) => ({ ...prev, calculation_base: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              >
                <option value="">Seleccionar</option>
                <option value="attendance">Asistencia</option>
                <option value="enrollment">Inscripcion</option>
              </select>
            </label>
          ) : null}

          {form.payment_type === 'per_plan_price' ? (
            <label className="space-y-1 text-sm">
              <span className="text-brand-muted">¿Sobre quién se calcula?</span>
              <select
                value={form.per_plan_price_base}
                onChange={(event) => setForm((prev) => ({ ...prev, per_plan_price_base: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              >
                <option value="">Seleccionar base</option>
                <option value="present_attendees">Por asistencia (solo presentes)</option>
                <option value="active_enrollments">Por reserva (inscritos activos)</option>
              </select>
            </label>
          ) : null}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={Boolean(form.is_active)}
              onChange={(event) => setForm((prev) => ({ ...prev, is_active: event.target.checked }))}
            />
            <span>Regla activa</span>
          </label>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              disabled={working}
              onClick={() => {
                setFormOpen(false)
                clearForm()
              }}
              className="rounded border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:text-brand-white disabled:opacity-50"
            >
              Cerrar
            </button>
            <button
              type="submit"
              disabled={working}
              className="rounded bg-brand-orange px-3 py-1.5 text-sm font-semibold text-black transition hover:brightness-110 disabled:opacity-50"
            >
              {working ? 'Guardando...' : editing ? 'Guardar cambios' : 'Guardar'}
            </button>
          </div>
        </form>
      </FormModal>

      <FormModal
        open={assignmentsOpen}
        title={assignmentsRule ? `Asignaciones - Regla #${assignmentsRule.id}` : 'Asignaciones'}
        closeDisabled={working}
        onClose={() => {
          setAssignmentsOpen(false)
          setAssignmentsRule(null)
          setAssignmentItems([])
          setAssignmentSelectedIds([])
        }}
      >
        <form onSubmit={saveAssignments} className="space-y-3">
          <p className="text-sm text-brand-muted">Selecciona profesores que pueden usar esta regla.</p>
          <div className="max-h-72 space-y-2 overflow-auto rounded-lg border border-brand-line bg-black/20 p-3">
            {assignmentItems.map((item) => {
              const checked = assignmentSelectedIds.includes(item.teacher_id)
              return (
                <label key={item.teacher_id} className="flex items-center justify-between gap-3 rounded border border-brand-line/40 p-2 text-sm">
                  <span className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) => {
                        if (event.target.checked) {
                          setAssignmentSelectedIds((prev) => (prev.includes(item.teacher_id) ? prev : [...prev, item.teacher_id]))
                        } else {
                          setAssignmentSelectedIds((prev) => prev.filter((id) => id !== item.teacher_id))
                        }
                      }}
                    />
                    <span>{item.teacher_name}</span>
                  </span>
                  <span className="text-xs text-brand-muted">{item.is_assigned ? 'Asignado' : 'No asignado'}</span>
                </label>
              )
            })}
            {assignmentItems.length === 0 ? <p className="text-sm text-brand-muted">No hay profesores disponibles.</p> : null}
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              disabled={working}
              onClick={() => {
                setAssignmentsOpen(false)
                setAssignmentsRule(null)
                setAssignmentItems([])
                setAssignmentSelectedIds([])
              }}
              className="rounded border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:text-brand-white disabled:opacity-50"
            >
              Cerrar
            </button>
            <button
              type="submit"
              disabled={working}
              className="rounded bg-brand-orange px-3 py-1.5 text-sm font-semibold text-black transition hover:brightness-110 disabled:opacity-50"
            >
              {working ? 'Guardando...' : 'Guardar asignaciones'}
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deletingRule)}
        title="Eliminar regla de pago"
        description="Eliminar regla de pago?"
        confirmLabel="Eliminar"
        loading={working}
        onConfirm={handleDelete}
        onCancel={() => {
          if (!working) {
            setDeletingRule(null)
          }
        }}
      />
    </div>
  )
}
