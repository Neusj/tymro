import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { branchesApi, organizationsApi, usersApi } from '../api/client'
import Avatar from '../components/Avatar'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FilterDropdown from '../components/FilterDropdown'
import FilterPanel from '../components/FilterPanel'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import RoleBadge from '../components/RoleBadge'
import ValueBadge from '../components/ui/ValueBadge'

const userInitialForm = {
  username: '',
  first_name: '',
  last_name: '',
  email: '',
  role: 'teacher',
  organization: '',
  branch: '',
  password: '',
  phone: '',
  profile_image: null,
  is_active_member: true,
  is_active: true,
}

const editableRoles = ['superadmin', 'gym_admin', 'teacher', 'student']

const roleLabels = { superadmin: 'Superadmin', gym_admin: 'Gym Admin', teacher: 'Profesor', student: 'Alumno' }
const roleFilterOptions = [{ value: '', label: 'Todos' }, ...editableRoles.map((role) => ({ value: role, label: roleLabels[role] }))]

export default function SuperadminUsersPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [organizations, setOrganizations] = useState([])
  const [branches, setBranches] = useState([])
  const [users, setUsers] = useState([])
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState(userInitialForm)
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)

  const organizationFilter = searchParams.get('organization_id') || ''
  const roleFilter = searchParams.get('role') || ''

  const loadOrganizations = async () => {
    const data = await organizationsApi.list()
    setOrganizations(data)
  }

  const loadUsers = async () => {
    if (!organizationFilter) {
      setUsers([])
      return
    }

    const params = { organization_id: organizationFilter }
    if (roleFilter) {
      params.role = roleFilter
    }

    try {
      const data = await usersApi.list(params)
      setUsers(data)
      setError('')
    } catch (err) {
      setUsers([])
      setError(err?.response?.data?.detail || 'No se pudo cargar usuarios.')
    }
  }

  const loadBranches = async () => {
    const data = await branchesApi.list()
    setBranches(data)
  }

  useEffect(() => {
    loadOrganizations()
    loadBranches()
  }, [])

  useEffect(() => {
    loadUsers()
  }, [organizationFilter, roleFilter])

  const filteredBranches = useMemo(
    () => branches.filter((branch) => String(branch.organization) === String(form.organization || organizationFilter)),
    [branches, form.organization, organizationFilter],
  )

  const openCreate = () => {
    setEditing(null)
    setForm({
      ...userInitialForm,
      organization: organizationFilter || '',
    })
    setModalOpen(true)
  }

  const openEdit = (user) => {
    setEditing(user)
    setForm({
      username: user.username || '',
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      email: user.email || '',
      role: user.role || 'student',
      organization: user.organization || organizationFilter,
      branch: user.branch || '',
      password: '',
      phone: user.phone || '',
      profile_image: null,
      is_active_member: Boolean(user.is_active_member),
      is_active: Boolean(user.is_active),
    })
    setModalOpen(true)
  }

  const saveUser = async (event) => {
    event.preventDefault()
    const payload = { ...form }
    if (!payload.profile_image) {
      delete payload.profile_image
    }
    if (!payload.password) {
      delete payload.password
    }
    if (editing) {
      await usersApi.update(editing.id, payload, true)
    } else {
      await usersApi.create(payload, true)
    }
    setModalOpen(false)
    await loadUsers()
  }

  const removeUser = async () => {
    if (!deleting) {
      return
    }
    await usersApi.remove(deleting.id)
    setDeleting(null)
    await loadUsers()
  }

  const toggleActive = async (row) => {
    await usersApi.update(row.id, { is_active: !row.is_active })
    await loadUsers()
  }

  const setFilter = (key, value) => {
    const next = new URLSearchParams(searchParams)
    if (value) {
      next.set(key, value)
    } else {
      next.delete(key)
    }
    setSearchParams(next)
  }

  const columns = [
    {
      key: 'user',
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
    { key: 'branch', label: 'Sucursal', render: (row) => row.branch_detail?.name || 'Sin sucursal' },
    { key: 'status', label: 'Estado', render: (row) => <ValueBadge kind="user_status" value={row.is_active ? 'active' : 'inactive'} /> },
    {
      key: 'actions',
      label: 'Acciones',
      render: (row) => (
        <div className="flex gap-2">
          <button type="button" onClick={() => openEdit(row)} className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted">
            Editar
          </button>
          <button type="button" onClick={() => toggleActive(row)} className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted">
            {row.is_active ? 'Desactivar' : 'Activar'}
          </button>
          {row.role === 'student' ? (
            <button
              type="button"
              onClick={() => navigate(`/superadmin/plans/assign?organization_id=${row.organization || ''}&user_id=${row.id}`)}
              className="rounded border border-brand-blue/40 px-2 py-1 text-xs text-blue-200"
            >
              Planes
            </button>
          ) : null}
          <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
            Eliminar
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Superadmin · Usuarios"
        subtitle="Listado por organización (filtro obligatorio)."
        extra={
          <button
            type="button"
            disabled={!organizationFilter}
            onClick={openCreate}
            className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            Crear usuario
          </button>
        }
      />

      <section className="card-surface p-5">
        <FilterPanel
          activeCount={(organizationFilter ? 1 : 0) + (roleFilter ? 1 : 0)}
          onClear={() => setSearchParams(new URLSearchParams())}
        >
          <div className="flex flex-wrap items-end gap-2">
            <FilterDropdown
              label="Organización"
              value={organizationFilter}
              options={[{ value: '', label: 'Selecciona una organización' }, ...organizations.map((organization) => ({ value: String(organization.id), label: organization.name }))]}
              onChange={(value) => setFilter('organization_id', value)}
            />
            <FilterDropdown label="Rol" value={roleFilter} options={roleFilterOptions} onChange={(value) => setFilter('role', value)} />
          </div>
        </FilterPanel>
      </section>

      {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-100">{error}</p> : null}

      <section className="card-surface p-5">
        <DataTable columns={columns} data={users} />
      </section>

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? 'Editar usuario' : 'Crear usuario'}>
        <form onSubmit={saveUser} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span>Username</span>
            <input
              required
              value={form.username}
              onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Email</span>
            <input
              type="email"
              value={form.email}
              onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Nombre</span>
            <input
              value={form.first_name}
              onChange={(event) => setForm((prev) => ({ ...prev, first_name: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Apellido</span>
            <input
              value={form.last_name}
              onChange={(event) => setForm((prev) => ({ ...prev, last_name: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Rol</span>
            <select value={form.role} onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
              {editableRoles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Organización</span>
            <select
              value={form.organization}
              onChange={(event) => setForm((prev) => ({ ...prev, organization: event.target.value, branch: '' }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Sin organización</option>
              {organizations.map((organization) => (
                <option key={organization.id} value={organization.id}>
                  {organization.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Sucursal</span>
            <select value={form.branch} onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
              <option value="">Sin sucursal</option>
              {filteredBranches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Teléfono</span>
            <input value={form.phone} onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Contraseña {editing ? '(opcional)' : ''}</span>
            <input
              type="password"
              value={form.password}
              onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Foto</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setForm((prev) => ({ ...prev, profile_image: event.target.files?.[0] || null }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((prev) => ({ ...prev, is_active: event.target.checked }))} />
            Usuario activo
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_active_member}
              onChange={(event) => setForm((prev) => ({ ...prev, is_active_member: event.target.checked }))}
            />
            Miembro activo
          </label>
          <div className="md:col-span-2 flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Guardar
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar usuario"
        description={`Se eliminará ${deleting?.username || 'este usuario'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeUser}
      />
    </div>
  )
}
