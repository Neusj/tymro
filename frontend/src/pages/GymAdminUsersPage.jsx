import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { branchesApi, usersApi } from '../api/client'
import Avatar from '../components/Avatar'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FilterDropdown from '../components/FilterDropdown'
import FilterPanel from '../components/FilterPanel'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import RoleBadge from '../components/RoleBadge'
import ValueBadge from '../components/ui/ValueBadge'
import { extractApiErrorMessage } from '../utils/apiErrors'
import { formatRut, toCanonical } from '../utils/rut'

const userInitialForm = {
  first_name: '',
  last_name: '',
  email: '',
  role: '',
  rut: '',
  branch: '',
  password: '',
  phone: '',
  profile_image: null,
  is_active_member: true,
  pays_enrollment_fee: true,
  is_active: true,
}

export default function GymAdminUsersPage() {
  const navigate = useNavigate()
  const [branches, setBranches] = useState([])
  const [users, setUsers] = useState([])
  const [assignableRoles, setAssignableRoles] = useState([])
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(userInitialForm)
  const [formError, setFormError] = useState('')
  const [deleting, setDeleting] = useState(null)
  const [roleFilter, setRoleFilter] = useState('')

  const loadData = async () => {
    try {
      const [branchesData, usersData] = await Promise.all([branchesApi.list(), usersApi.list(roleFilter ? { role: roleFilter } : {})])
      setBranches(branchesData)
      setUsers(usersData)
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo cargar usuarios.'))
    }
  }

  useEffect(() => {
    usersApi
      .assignableRoles()
      .then(setAssignableRoles)
      .catch((apiError) => setError(extractApiErrorMessage(apiError, 'No se pudo cargar los roles disponibles.')))
  }, [])

  useEffect(() => {
    loadData()
  }, [roleFilter])

  const roleFilterOptions = useMemo(() => [{ value: '', label: 'Todos' }, ...assignableRoles], [assignableRoles])

  const canManage = (role) => assignableRoles.some((option) => option.value === role)

  const defaultRoleValue = () => (assignableRoles.find((option) => option.value === 'teacher') || assignableRoles[0])?.value || ''

  const openCreate = () => {
    setEditing(null)
    setForm({ ...userInitialForm, role: defaultRoleValue() })
    setFormError('')
    setModalOpen(true)
  }

  const openEdit = (user) => {
    setEditing(user)
    setForm({
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      email: user.email || '',
      role: user.role || '',
      rut: formatRut(user.rut || ''),
      branch: user.branch || '',
      password: '',
      phone: user.phone || '',
      profile_image: null,
      is_active_member: Boolean(user.is_active_member),
      pays_enrollment_fee: user.pays_enrollment_fee !== false,
      is_active: Boolean(user.is_active),
    })
    setFormError('')
    setModalOpen(true)
  }

  const submitUser = async (event) => {
    event.preventDefault()
    // Validación de dígito verificador antes de enviar (el backend re-valida).
    const canonicalRut = toCanonical(form.rut)
    if (!canonicalRut) {
      setFormError('RUT inválido. Revisa el número y el dígito verificador.')
      return
    }
    const payload = { ...form, rut: canonicalRut }
    if (!payload.profile_image) {
      delete payload.profile_image
    }
    if (!payload.password) {
      delete payload.password
    }

    try {
      if (editing) {
        await usersApi.update(editing.id, payload, true)
      } else {
        await usersApi.create(payload, true)
      }
      setError('')
      setModalOpen(false)
      await loadData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No tienes permisos para esa acción.'))
      setModalOpen(false)
    }
  }

  const removeUser = async () => {
    if (!deleting) {
      return
    }
    try {
      await usersApi.remove(deleting.id)
      setError('')
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No tienes permisos para esa acción.'))
    }
    setDeleting(null)
    await loadData()
  }

  const toggleActive = async (user) => {
    try {
      await usersApi.update(user.id, { is_active: !user.is_active })
      setError('')
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No tienes permisos para esa acción.'))
    }
    await loadData()
  }

  const columns = useMemo(
    () => [
      {
        key: 'user',
        label: 'Usuario',
        render: (row) => (
          <div className="flex items-center gap-2">
            <Avatar src={row.profile_image} name={`${row.first_name} ${row.last_name}`} size="sm" />
            <div>
              <p className="font-semibold">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || row.email}</p>
              <p className="text-xs text-brand-muted">{row.email}</p>
            </div>
          </div>
        ),
      },
      { key: 'role', label: 'Rol', mobile: 'meta', render: (row) => <RoleBadge role={row.role} /> },
      { key: 'branch', label: 'Sucursal', mobile: 'secondary', render: (row) => row.branch_detail?.name || 'Sin sucursal' },
      { key: 'status', label: 'Estado', mobile: 'meta', render: (row) => <ValueBadge kind="user_status" value={row.is_active ? 'active' : 'inactive'} /> },
      {
        key: 'enrollment_fee',
        label: 'Matricula',
        mobile: 'secondary',
        render: (row) => (row.pays_enrollment_fee === false ? 'Exento' : 'Se cobra'),
      },
      {
        key: 'actions',
        label: 'Acciones',
        mobilePrimary: (row) =>
          canManage(row.role) ? (
            <button type="button" onClick={() => openEdit(row)} className="rounded-lg border border-brand-blue bg-brand-blue/10 px-3 py-2 text-xs font-semibold text-brand-white">
              Editar
            </button>
          ) : null,
        render: (row) =>
          canManage(row.role) ? (
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
                  onClick={() => navigate(`/gym-admin/plans/assign?user_id=${row.id}`)}
                  className="rounded border border-brand-blue/40 px-2 py-1 text-xs text-blue-200"
                >
                  Planes
                </button>
              ) : null}
              {row.role === 'student' ? (
                <button
                  type="button"
                  onClick={() => navigate(`/gym-admin/students/overview?student_id=${row.id}`)}
                  className="rounded border border-brand-orange/40 px-2 py-1 text-xs text-amber-200"
                >
                  Vista integral
                </button>
              ) : null}
              <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
                Eliminar
              </button>
            </div>
          ) : (
            <span className="text-xs text-brand-muted">Solo lectura</span>
          ),
      },
    ],
    [assignableRoles],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Usuarios"
        subtitle="CRUD de usuarios de tu organización."
        extra={
          assignableRoles.length > 0 ? (
            <button type="button" onClick={openCreate} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Crear usuario
            </button>
          ) : null
        }
      />

      <section className="card-surface p-5">
        <FilterPanel activeCount={roleFilter ? 1 : 0} onClear={() => setRoleFilter('')}>
          <FilterDropdown label="Rol" value={roleFilter} options={roleFilterOptions} onChange={setRoleFilter} />
        </FilterPanel>
      </section>

      {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 px-4 py-3 text-sm text-red-200">{error}</p> : null}

      <section className="card-surface p-5">
        <DataTable columns={columns} data={users} />
      </section>

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? 'Editar usuario' : 'Crear usuario'}>
        <form onSubmit={submitUser} className="grid gap-3 md:grid-cols-2">
          {formError ? (
            <p className="md:col-span-2 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">
              {formError}
            </p>
          ) : null}
          <label className="space-y-1 text-sm">
            <span>Nombre</span>
            <input
              required
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
            <span>Email</span>
            <input
              required
              type="email"
              value={form.email}
              onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>RUT</span>
            <input
              required
              value={form.rut}
              onChange={(event) => setForm((prev) => ({ ...prev, rut: formatRut(event.target.value) }))}
              placeholder="12.345.678-5"
              inputMode="text"
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Rol</span>
            <select value={form.role} onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
              {assignableRoles.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Sucursal</span>
            <select value={form.branch} onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
              <option value="">Sin sucursal</option>
              {branches.map((branch) => (
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
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.pays_enrollment_fee}
              onChange={(event) => setForm((prev) => ({ ...prev, pays_enrollment_fee: event.target.checked }))}
            />
            Cobra matricula anual
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
        description={`Se eliminará ${deleting?.email || `${deleting?.first_name || ''} ${deleting?.last_name || ''}`.trim() || 'este usuario'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeUser}
      />
    </div>
  )
}
