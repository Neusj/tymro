import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { branchesApi, organizationsApi, usersApi } from '../api/client'
import Avatar from '../components/Avatar'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import RoleBadge from '../components/RoleBadge'
import ValueBadge from '../components/ui/ValueBadge'

const branchFormInitial = {
  name: '',
  code: '',
  address: '',
  logo: null,
}

export default function SuperadminOrganizationDetailPage() {
  const { id } = useParams()
  const [organization, setOrganization] = useState(null)
  const [branches, setBranches] = useState([])
  const [users, setUsers] = useState([])
  const [branchModal, setBranchModal] = useState(false)
  const [branchForm, setBranchForm] = useState(branchFormInitial)
  const [editingBranch, setEditingBranch] = useState(null)
  const [branchToDelete, setBranchToDelete] = useState(null)

  const loadData = async () => {
    const [organizationData, branchData, userData] = await Promise.all([
      organizationsApi.retrieve(id),
      branchesApi.list(),
      usersApi.list({ organization_id: id }),
    ])

    setOrganization(organizationData)
    setBranches(branchData.filter((branch) => String(branch.organization) === String(id)))
    setUsers(userData)
  }

  useEffect(() => {
    loadData()
  }, [id])

  const openCreateBranch = () => {
    setEditingBranch(null)
    setBranchForm(branchFormInitial)
    setBranchModal(true)
  }

  const openEditBranch = (branch) => {
    setEditingBranch(branch)
    setBranchForm({
      name: branch.name || '',
      code: branch.code || '',
      address: branch.address || '',
      logo: null,
    })
    setBranchModal(true)
  }

  const submitBranch = async (event) => {
    event.preventDefault()
    const payload = {
      ...branchForm,
      organization: id,
    }
    if (!payload.logo) {
      delete payload.logo
    }
    if (editingBranch) {
      await branchesApi.update(editingBranch.id, payload, true)
    } else {
      await branchesApi.create(payload, true)
    }
    setBranchModal(false)
    await loadData()
  }

  const deleteBranch = async () => {
    if (!branchToDelete) {
      return
    }
    await branchesApi.remove(branchToDelete.id)
    setBranchToDelete(null)
    await loadData()
  }

  const userColumns = [
    {
      key: 'name',
      label: 'Usuario',
      render: (row) => (
        <div className="flex items-center gap-2">
          <Avatar src={row.profile_image} name={`${row.first_name} ${row.last_name}`} size="sm" />
          <div>
            <p className="font-semibold">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || row.username}</p>
            <p className="text-xs text-brand-muted">{row.email || row.username}</p>
          </div>
        </div>
      ),
    },
    { key: 'role', label: 'Rol', render: (row) => <RoleBadge role={row.role} /> },
    { key: 'branch_detail', label: 'Sucursal', render: (row) => row.branch_detail?.name || 'Sin sucursal' },
    { key: 'is_active', label: 'Estado', render: (row) => <ValueBadge kind="user_status" value={row.is_active ? 'active' : 'inactive'} /> },
  ]

  const branchColumns = [
    { key: 'name', label: 'Nombre' },
    { key: 'code', label: 'Código' },
    { key: 'address', label: 'Dirección' },
    {
      key: 'actions',
      label: 'Acciones',
      render: (row) => (
        <div className="flex gap-2">
          <button type="button" onClick={() => openEditBranch(row)} className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted">
            Editar
          </button>
          <button type="button" onClick={() => setBranchToDelete(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
            Eliminar
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={`Organización · ${organization?.name || ''}`}
        subtitle="Contexto de sucursales y usuarios de esta organización."
        back={{ to: '/superadmin/organizations', label: 'Organizaciones' }}
        extra={
          <div className="flex gap-2">
            <button type="button" onClick={openCreateBranch} className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-white">
              Nueva sucursal
            </button>
            <Link to={`/superadmin/users?organization_id=${id}`} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Gestionar usuarios
            </Link>
          </div>
        }
      />

      <section className="card-surface p-5">
        <div className="flex items-center gap-3">
          <Avatar src={organization?.logo} name={organization?.name} size="lg" />
          <div>
            <p className="text-lg font-semibold">{organization?.name}</p>
            <p className="text-sm text-brand-muted">
              {organization?.city || 'Sin ciudad'} · {organization?.country || 'Sin país'}
            </p>
          </div>
        </div>
      </section>

      <section className="card-surface p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="panel-title">Sucursales</h2>
        </div>
        <DataTable columns={branchColumns} data={branches} />
      </section>

      <section className="card-surface p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="panel-title">Usuarios</h2>
          <Link to={`/superadmin/users?organization_id=${id}`} className="text-sm text-brand-orange">
            Ir a gestión completa
          </Link>
        </div>
        <DataTable columns={userColumns} data={users} />
      </section>

      <FormModal open={branchModal} onClose={() => setBranchModal(false)} title={editingBranch ? 'Editar sucursal' : 'Nueva sucursal'}>
        <form onSubmit={submitBranch} className="grid gap-3">
          <label className="space-y-1 text-sm">
            <span>Nombre</span>
            <input
              required
              value={branchForm.name}
              onChange={(event) => setBranchForm((prev) => ({ ...prev, name: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Código</span>
            <input
              value={branchForm.code}
              onChange={(event) => setBranchForm((prev) => ({ ...prev, code: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Dirección</span>
            <input
              value={branchForm.address}
              onChange={(event) => setBranchForm((prev) => ({ ...prev, address: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Logo</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setBranchForm((prev) => ({ ...prev, logo: event.target.files?.[0] || null }))}
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
        open={Boolean(branchToDelete)}
        title="Eliminar sucursal"
        description={`Se eliminará ${branchToDelete?.name || 'esta sucursal'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setBranchToDelete(null)}
        onConfirm={deleteBranch}
      />
    </div>
  )
}
