import { useEffect, useState } from 'react'
import { branchesApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import { canManageAdmin } from '../utils/roles'

const initialForm = {
  name: '',
  code: '',
  address: '',
  logo: null,
  primary_color: '',
  secondary_color: '',
}

export default function GymAdminBranchesPage() {
  const { user } = useAuth()
  const canManage = canManageAdmin(user?.role)
  const [branches, setBranches] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(initialForm)
  const [deleting, setDeleting] = useState(null)

  const loadData = async () => {
    const data = await branchesApi.list()
    setBranches(data)
  }

  useEffect(() => {
    loadData()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(initialForm)
    setModalOpen(true)
  }

  const openEdit = (branch) => {
    setEditing(branch)
    setForm({
      name: branch.name || '',
      code: branch.code || '',
      address: branch.address || '',
      logo: null,
      primary_color: branch.primary_color || '',
      secondary_color: branch.secondary_color || '',
    })
    setModalOpen(true)
  }

  const submit = async (event) => {
    event.preventDefault()
    const payload = { ...form }
    if (!payload.logo) {
      delete payload.logo
    }

    if (editing) {
      await branchesApi.update(editing.id, payload, true)
    } else {
      await branchesApi.create(payload, true)
    }
    setModalOpen(false)
    await loadData()
  }

  const removeBranch = async () => {
    if (!deleting) {
      return
    }
    await branchesApi.remove(deleting.id)
    setDeleting(null)
    await loadData()
  }

  const columns = [
    { key: 'name', label: 'Nombre' },
    { key: 'code', label: 'Código' },
    { key: 'address', label: 'Dirección' },
    { key: 'primary_color', label: 'Color primario', render: (row) => row.primary_color || '-' },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: 'Acciones',
            render: (row) => (
              <div className="flex gap-2">
                <button type="button" onClick={() => openEdit(row)} className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted">
                  Editar
                </button>
                <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
                  Eliminar
                </button>
              </div>
            ),
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Sucursales"
        subtitle="CRUD de sucursales dentro de tu organización."
        extra={
          canManage ? (
            <button type="button" onClick={openCreate} className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-white">
              Nueva sucursal
            </button>
          ) : null
        }
      />

      <section className="card-surface p-5">
        <DataTable columns={columns} data={branches} />
      </section>

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? 'Editar sucursal' : 'Nueva sucursal'}>
        <form onSubmit={submit} className="grid gap-3">
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
            <span>Código</span>
            <input value={form.code} onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Dirección</span>
            <input
              value={form.address}
              onChange={(event) => setForm((prev) => ({ ...prev, address: event.target.value }))}
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
          <label className="space-y-1 text-sm">
            <span>Logo</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setForm((prev) => ({ ...prev, logo: event.target.files?.[0] || null }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <div className="flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Guardar
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar sucursal"
        description={`Se eliminará ${deleting?.name || 'esta sucursal'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeBranch}
      />
    </div>
  )
}
