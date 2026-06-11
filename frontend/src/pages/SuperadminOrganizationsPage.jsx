import { useEffect, useMemo, useState } from 'react'
import { dashboardApi, organizationsApi } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import OrganizationCard from '../components/OrganizationCard'
import StatCard from '../components/StatCard'

const emptySummary = {
  organizations: 0,
  branches: 0,
  users: 0,
  gym_admins: 0,
}

const initialForm = {
  name: '',
  slug: '',
  country: '',
  city: '',
  primary_color: '',
  secondary_color: '',
  logo: null,
}

export default function SuperadminOrganizationsPage() {
  const [summary, setSummary] = useState(emptySummary)
  const [organizations, setOrganizations] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState(initialForm)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(null)
  const [confirmLoading, setConfirmLoading] = useState(false)

  const modalTitle = useMemo(() => (editing ? 'Editar organización' : 'Nueva organización'), [editing])

  const loadData = async () => {
    setLoading(true)
    try {
      const [summaryData, organizationsData] = await Promise.all([dashboardApi.summary(), organizationsApi.list()])
      setSummary({ ...emptySummary, ...summaryData })
      setOrganizations(organizationsData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(initialForm)
    setError('')
    setModalOpen(true)
  }

  const openEdit = (organization) => {
    setEditing(organization)
    setForm({
      name: organization.name || '',
      slug: organization.slug || '',
      country: organization.country || '',
      city: organization.city || '',
      primary_color: organization.primary_color || '',
      secondary_color: organization.secondary_color || '',
      logo: null,
      is_active: Boolean(organization.is_active),
      public_registration_enabled: Boolean(organization.public_registration_enabled),
    })
    setError('')
    setModalOpen(true)
  }

  const onSubmit = async (event) => {
    event.preventDefault()
    setError('')
    try {
      const payload = {
        ...form,
      }

      if (!payload.logo) {
        delete payload.logo
      }

      if (editing) {
        await organizationsApi.update(editing.id, payload, true)
      } else {
        await organizationsApi.create(payload, true)
      }

      setModalOpen(false)
      await loadData()
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo guardar la organización.')
    }
  }

  const confirmDelete = async () => {
    if (!deleting) {
      return
    }
    setConfirmLoading(true)
    try {
      await organizationsApi.remove(deleting.id)
      setDeleting(null)
      await loadData()
    } finally {
      setConfirmLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Superadmin · Organizaciones"
        subtitle="Métricas globales y gestión de organizaciones. El detalle de usuarios ocurre por organización."
        extra={
          <button type="button" onClick={openCreate} className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-white">
            Nueva organización
          </button>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="Organizaciones" value={summary.organizations} accent="orange" />
        <StatCard title="Sucursales" value={summary.branches} accent="blue" />
        <StatCard title="Usuarios" value={summary.users} accent="red" />
        <StatCard title="Gym Admins" value={summary.gym_admins} accent="orange" />
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {organizations.map((organization) => (
          <div key={organization.id} className="space-y-2">
            <OrganizationCard organization={organization} />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => openEdit(organization)}
                className="rounded-lg border border-brand-line px-3 py-1.5 text-xs text-brand-muted hover:text-brand-white"
              >
                Editar
              </button>
              <button
                type="button"
                onClick={() => setDeleting(organization)}
                className="rounded-lg border border-brand-red/40 px-3 py-1.5 text-xs text-red-200"
              >
                Eliminar
              </button>
            </div>
          </div>
        ))}
      </section>

      {!loading && organizations.length === 0 ? <p className="text-sm text-brand-muted">No hay organizaciones registradas.</p> : null}

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title={modalTitle}>
        <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span>Nombre</span>
            <input
              required
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Slug</span>
            <input
              required
              value={form.slug}
              onChange={(event) => setForm((prev) => ({ ...prev, slug: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>País</span>
            <input
              value={form.country}
              onChange={(event) => setForm((prev) => ({ ...prev, country: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Ciudad</span>
            <input
              value={form.city}
              onChange={(event) => setForm((prev) => ({ ...prev, city: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Color primario</span>
            <input
              placeholder="#dc2626"
              value={form.primary_color}
              onChange={(event) => setForm((prev) => ({ ...prev, primary_color: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Color secundario</span>
            <input
              placeholder="#2563eb"
              value={form.secondary_color}
              onChange={(event) => setForm((prev) => ({ ...prev, secondary_color: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm md:col-span-2">
            <span>Logo</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setForm((prev) => ({ ...prev, logo: event.target.files?.[0] || null }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          {editing ? (
            <div className="md:col-span-2 space-y-3 rounded-xl border border-brand-line bg-black/20 p-3">
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(form.is_active)}
                  onChange={(event) => setForm((prev) => ({ ...prev, is_active: event.target.checked }))}
                  className="mt-1 h-4 w-4 shrink-0"
                />
                <span>
                  Organización activa
                  <span className="mt-0.5 block text-xs text-brand-muted">
                    Si está desactivada, la organización no opera.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(form.public_registration_enabled)}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, public_registration_enabled: event.target.checked }))
                  }
                  className="mt-1 h-4 w-4 shrink-0"
                />
                <span>
                  Permitir registro público (clase de prueba / QR)
                  <span className="mt-0.5 block text-xs text-brand-muted">
                    Si está apagado, el link/QR de clase de prueba no funciona.
                  </span>
                </span>
              </label>
            </div>
          ) : null}
          {error ? <p className="text-sm text-red-200 md:col-span-2">{error}</p> : null}
          <div className="md:col-span-2 flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Guardar
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar organización"
        description={`Se eliminará ${deleting?.name || 'esta organización'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={confirmDelete}
        loading={confirmLoading}
      />
    </div>
  )
}
