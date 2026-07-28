import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createPlan, getPlans, organizationsApi, removePlan, updatePlan } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import ValueBadge from '../components/ui/ValueBadge'

const initialForm = {
  name: '',
  plan_type: 'monthly',
  total_classes: 8,
  unlimited_classes: false,
  duration_days: 30,
  price: 0,
  discount_percentage: 0,
  is_public: true,
  is_active: true,
  organization: '',
}

const planTypeLabel = {
  monthly: 'Mensual',
  pack: 'Pack',
  single_class: 'Clase suelta',
  trial: 'Trial',
  giftcard: 'Giftcard',
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

function toBool(value, fallback = false) {
  if (typeof value === 'boolean') {
    return value
  }
  if (typeof value === 'number') {
    return value !== 0
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'on', 'active'].includes(normalized)) {
      return true
    }
    if (['false', '0', 'no', 'off', 'inactive'].includes(normalized)) {
      return false
    }
  }
  return fallback
}

export default function PlanListPage({
  title = 'Planes',
  subtitle = 'Listado y creación de planes.',
  showMembershipsAction = false,
  membershipsBasePath = '/gym-admin/plans',
}) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [plans, setPlans] = useState([])
  const [organizations, setOrganizations] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [form, setForm] = useState(initialForm)

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getPlans()
      setPlans(data)
      if (user?.role === 'superadmin') {
        const orgs = await organizationsApi.list()
        setOrganizations(orgs)
      }
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar los planes.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')
    setSaving(true)
    try {
      const normalizedName = String(form.name ?? '').trim()
      if (!normalizedName) {
        setError('El nombre del plan es obligatorio.')
        return
      }
      const unlimitedClasses = toBool(form.unlimited_classes, false)
      const payload = {
        name: normalizedName,
        plan_type: form.plan_type || 'monthly',
        total_classes: unlimitedClasses ? 0 : Number(form.total_classes),
        unlimited_classes: unlimitedClasses,
        duration_days: Number(form.duration_days),
        price: Number(form.price),
        discount_percentage: Number(form.discount_percentage),
        is_public: toBool(form.is_public, true),
        is_active: toBool(form.is_active, true),
      }
      if (user?.role === 'superadmin') {
        payload.organization = form.organization
      }
      let response
      if (editing) {
        response = await updatePlan(editing.id, payload)
      } else {
        response = await createPlan(payload)
      }
      setForm(initialForm)
      setEditing(null)
      setOpen(false)
      await loadData()
      setNotice(editing ? `Plan actualizado: ${response?.name || 'ok'}.` : `Plan creado: ${response?.name || 'ok'}.`)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, editing ? 'No se pudo actualizar el plan.' : 'No se pudo crear el plan.'))
    } finally {
      setSaving(false)
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm(initialForm)
    setOpen(true)
  }

  const openEdit = (plan) => {
    setEditing(plan)
    setForm({
      name: plan.name || '',
      plan_type: plan.plan_type || 'monthly',
      total_classes: plan.total_classes ?? 0,
      unlimited_classes: toBool(plan.unlimited_classes, false),
      duration_days: plan.duration_days ?? 30,
      price: plan.price ?? 0,
      discount_percentage: plan.discount_percentage ?? 0,
      is_public: toBool(plan.is_public, true),
      is_active: toBool(plan.is_active, true),
      organization: plan.organization || '',
    })
    setOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleting) {
      return
    }
    setError('')
    setNotice('')
    setSaving(true)
    try {
      await removePlan(deleting.id)
      setNotice(`Plan eliminado: ${deleting.name || deleting.id}.`)
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      // El 400 de la guarda de cascada viene ACOMPANADO de una escritura: el backend
      // desactiva el plan (is_active=false) y lo dice en el mensaje. Sin recargar aca, la
      // tabla seguia mostrando "Activo" mientras el aviso decia que se habia desactivado.
      const message = firstApiError(apiError?.response?.data, 'No se pudo eliminar el plan.')
      setDeleting(null)
      // El setError va DESPUES del loadData a proposito: loadData arranca con setError('')
      // y borraria el motivo, dejando al admin con el plan desactivado y sin explicacion.
      await loadData()
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'name', label: 'Nombre' },
      ...(user?.role === 'superadmin' ? [{ key: 'organization_name', label: 'Organizacion' }] : []),
      { key: 'plan_type', label: 'Tipo', render: (row) => planTypeLabel[row.plan_type] || row.plan_type || '-' },
      { key: 'total_classes', label: 'Clases', render: (row) => (row.unlimited_classes ? 'Ilimitado' : row.total_classes) },
      { key: 'duration_days', label: 'Duración (días)' },
      { key: 'price', label: 'Precio', render: (row) => `$${Number(row.price || 0).toFixed(0)}` },
      { key: 'discount_percentage', label: 'Desc. %', render: (row) => `${Number(row.discount_percentage || 0)}%` },
      { key: 'is_public', label: 'Público/Privado', render: (row) => (row.is_public ? 'Público' : 'Privado') },
      { key: 'is_active', label: 'Activo', render: (row) => <ValueBadge kind="user_status" value={row.is_active ? 'active' : 'inactive'} /> },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <div className="flex gap-2">
            {showMembershipsAction ? (
              <button
                type="button"
                onClick={() => navigate(`${membershipsBasePath}/${row.id}/memberships`)}
                className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted"
              >
                Ver membresías
              </button>
            ) : null}
            <button type="button" onClick={() => openEdit(row)} className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted">
              Editar
            </button>
            <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
              Eliminar
            </button>
          </div>
        ),
      },
    ],
    [membershipsBasePath, navigate, openEdit, showMembershipsAction, user?.role],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={title}
        subtitle={subtitle}
        extra={
          <button type="button" onClick={openCreate} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
            Crear plan
          </button>
        }
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}
      <p className="text-xs text-brand-muted">Planes cargados: {plans.length}</p>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={plans} loading={loading} />
      </section>

      <FormModal
        open={open}
        onClose={() => {
          setOpen(false)
          setEditing(null)
          setForm(initialForm)
        }}
        title={editing ? 'Editar plan' : 'Crear plan'}
      >
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
          {user?.role === 'superadmin' ? (
            <label className="space-y-1 text-sm md:col-span-2">
              <span>Organizacion</span>
              <select
                required
                value={form.organization}
                onChange={(event) => setForm((prev) => ({ ...prev, organization: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              >
                <option value="">Selecciona organizacion</option>
                {organizations.map((organization) => (
                  <option key={organization.id} value={organization.id}>
                    {organization.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="space-y-1 text-sm">
            <span>Tipo</span>
            <select value={form.plan_type} onChange={(event) => setForm((prev) => ({ ...prev, plan_type: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
              <option value="monthly">Mensual</option>
              <option value="pack">Pack</option>
              <option value="single_class">Clase suelta</option>
              <option value="trial">Trial</option>
              <option value="giftcard">Giftcard</option>
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Clases totales</span>
            <input
              required={!form.unlimited_classes}
              disabled={form.unlimited_classes}
              type="number"
              min="0"
              value={form.unlimited_classes ? '' : form.total_classes}
              placeholder={form.unlimited_classes ? 'Ilimitado' : ''}
              onChange={(event) => setForm((prev) => ({ ...prev, total_classes: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 disabled:opacity-50"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.unlimited_classes}
              onChange={(event) => setForm((prev) => ({ ...prev, unlimited_classes: event.target.checked }))}
            />
            Clases ilimitadas
          </label>
          <label className="space-y-1 text-sm">
            <span>Duración (días)</span>
            <input
              required
              type="number"
              min="1"
              value={form.duration_days}
              onChange={(event) => setForm((prev) => ({ ...prev, duration_days: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Precio</span>
            <input
              required
              type="number"
              min="0"
              step="0.01"
              value={form.price}
              onChange={(event) => setForm((prev) => ({ ...prev, price: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Descuento %</span>
            <input
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={form.discount_percentage}
              onChange={(event) => setForm((prev) => ({ ...prev, discount_percentage: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_public} onChange={(event) => setForm((prev) => ({ ...prev, is_public: event.target.checked }))} />
            Plan público
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((prev) => ({ ...prev, is_active: event.target.checked }))} />
            Plan activo
          </label>
          <div className="md:col-span-2 flex justify-end">
            <button type="submit" disabled={saving} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {saving ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar plan"
        description={`Se eliminará ${deleting?.name || 'este plan'}.`}
        confirmLabel="Eliminar"
        loading={saving}
        onCancel={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </div>
  )
}
