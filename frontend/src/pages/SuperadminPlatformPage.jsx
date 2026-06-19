import { useEffect, useMemo, useState } from 'react'
import { usersApi } from '../api/client'
import Avatar from '../components/Avatar'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import RoleBadge from '../components/RoleBadge'
import ValueBadge from '../components/ui/ValueBadge'
import { extractApiErrorMessage } from '../utils/apiErrors'
import { platformRoles, roleLabels } from '../utils/roles'

// Rol de plataforma que gestiona este panel (superadmin). roles.js es la fuente
// de la etiqueta; platformRoles define qué roles son de plataforma.
const PLATFORM_ROLE = platformRoles[0]

const initialForm = {
  first_name: '',
  last_name: '',
  email: '',
  password: '',
  phone: '',
  profile_image: null,
  is_active: true,
}

export default function SuperadminPlatformPage() {
  const [admins, setAdmins] = useState([])
  const [canCreate, setCanCreate] = useState(false)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(initialForm)
  const [deleting, setDeleting] = useState(null)

  const loadAdmins = async () => {
    try {
      const data = await usersApi.list({ role: PLATFORM_ROLE })
      setAdmins(data)
      setError('')
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo cargar los superadmins.'))
    }
  }

  useEffect(() => {
    // Solo se puede crear/gestionar superadmins si el actor tiene el rol de
    // plataforma entre sus roles asignables (lo decide el backend).
    usersApi
      .assignableRoles()
      .then((roles) => setCanCreate(roles.some((option) => option.value === PLATFORM_ROLE)))
      .catch((apiError) => setError(extractApiErrorMessage(apiError, 'No se pudo cargar los roles disponibles.')))
  }, [])

  useEffect(() => {
    loadAdmins()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(initialForm)
    setModalOpen(true)
  }

  const openEdit = (admin) => {
    setEditing(admin)
    setForm({
      first_name: admin.first_name || '',
      last_name: admin.last_name || '',
      email: admin.email || '',
      password: '',
      phone: admin.phone || '',
      profile_image: null,
      is_active: Boolean(admin.is_active),
    })
    setModalOpen(true)
  }

  const submit = async (event) => {
    event.preventDefault()
    const payload = { ...form, role: PLATFORM_ROLE }
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
      await loadAdmins()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No tienes permisos para esa acción.'))
      setModalOpen(false)
    }
  }

  const toggleActive = async (admin) => {
    try {
      await usersApi.update(admin.id, { is_active: !admin.is_active })
      setError('')
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No tienes permisos para esa acción.'))
    }
    await loadAdmins()
  }

  const removeAdmin = async () => {
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
    await loadAdmins()
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
      { key: 'role', label: 'Rol', render: (row) => <RoleBadge role={row.role} /> },
      { key: 'status', label: 'Estado', render: (row) => <ValueBadge kind="user_status" value={row.is_active ? 'active' : 'inactive'} /> },
      ...(canCreate
        ? [
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
                  <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
                    Eliminar
                  </button>
                </div>
              ),
            },
          ]
        : []),
    ],
    [canCreate],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Superadmin · Plataforma"
        subtitle={`Gestión de ${roleLabels[PLATFORM_ROLE]}s de la plataforma (independiente de los usuarios de organización).`}
        extra={
          canCreate ? (
            <button type="button" onClick={openCreate} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Crear {roleLabels[PLATFORM_ROLE].toLowerCase()}
            </button>
          ) : null
        }
      />

      {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 px-4 py-3 text-sm text-red-200">{error}</p> : null}

      <section className="card-surface p-5">
        <DataTable columns={columns} data={admins} />
      </section>

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? `Editar ${roleLabels[PLATFORM_ROLE].toLowerCase()}` : `Crear ${roleLabels[PLATFORM_ROLE].toLowerCase()}`}>
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
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
            <span>Teléfono</span>
            <input value={form.phone} onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Contraseña {editing ? '(opcional)' : ''}</span>
            <input
              type="password"
              required={!editing}
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
          <div className="md:col-span-2 flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Guardar
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title={`Eliminar ${roleLabels[PLATFORM_ROLE].toLowerCase()}`}
        description={`Se eliminará ${deleting?.email || `${deleting?.first_name || ''} ${deleting?.last_name || ''}`.trim() || 'este usuario'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeAdmin}
      />
    </div>
  )
}
