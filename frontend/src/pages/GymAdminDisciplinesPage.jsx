import { useEffect, useMemo, useState } from 'react'
import { disciplinesApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'
import { canManageOperational } from '../utils/roles'

const extractApiErrorMessage = (apiError, fallbackMessage) => {
  const detail = apiError?.response?.data

  if (!detail) {
    return fallbackMessage
  }

  if (typeof detail === 'string') {
    return detail
  }

  if (detail.detail && typeof detail.detail === 'string') {
    return detail.detail
  }

  const messages = []
  Object.values(detail).forEach((value) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (typeof item === 'string') {
          messages.push(item)
        }
      })
      return
    }

    if (typeof value === 'string') {
      messages.push(value)
    }
  })

  if (messages.length > 0) {
    return messages.join(' ')
  }

  return fallbackMessage
}

export default function GymAdminDisciplinesPage() {
  const { user } = useAuth()
  const canManage = canManageOperational(user?.role)
  const [disciplines, setDisciplines] = useState([])
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newActive, setNewActive] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editActive, setEditActive] = useState(true)
  const [deleting, setDeleting] = useState(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const data = await disciplinesApi.list()
      setDisciplines(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const openCreate = () => {
    setNewName('')
    setNewDescription('')
    setNewActive(true)
    setError('')
    setCreating(true)
  }

  const submitCreate = async (event) => {
    event.preventDefault()
    const name = newName.trim()
    if (!name) {
      return
    }
    setError('')
    try {
      const created = await disciplinesApi.create({
        name,
        description: newDescription.trim(),
        is_active: newActive,
      })
      setDisciplines((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setNewName('')
      setNewDescription('')
      setNewActive(true)
      setCreating(false)
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo crear la disciplina.'))
    }
  }

  const openEdit = (item) => {
    setEditing(item)
    setEditName(item.name || '')
    setEditDescription(item.description || '')
    setEditActive(item.is_active !== false)
    setError('')
  }

  const submitEdit = async (event) => {
    event.preventDefault()
    if (!editing) {
      return
    }

    setError('')
    try {
      await disciplinesApi.update(editing.id, {
        name: editName,
        description: editDescription.trim(),
        is_active: editActive,
      })
      setEditing(null)
      setEditName('')
      setEditDescription('')
      await loadData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo editar la disciplina.'))
    }
  }

  const removeItem = async () => {
    if (!deleting) {
      return
    }
    setError('')
    try {
      await disciplinesApi.remove(deleting.id)
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo eliminar la disciplina.'))
      setDeleting(null)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'name', label: 'Nombre' },
      {
        key: 'is_active',
        label: 'Estado',
        render: (row) => (
          <span
            className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${
              row.is_active === false
                ? 'border-brand-line bg-black/30 text-brand-muted'
                : 'border-success-line bg-success-soft text-success'
            }`}
          >
            {row.is_active === false ? 'Inactivo' : 'Activo'}
          </span>
        ),
      },
      ...(canManage
        ? [
            {
              key: 'actions',
              label: 'Acciones',
              render: (row) => (
                <>
                  <button type="button" onClick={() => openEdit(row)} className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue">
                    Editar
                  </button>
                  <button type="button" onClick={() => setDeleting(row)} className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10">
                    Eliminar
                  </button>
                </>
              ),
            },
          ]
        : []),
    ],
    [canManage],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Disciplinas"
        subtitle="Gestiona disciplinas como BJJ, Box, etc. para métricas futuras."
        back={{ to: '/gym-admin/class-templates', label: 'Gestión de clases' }}
      />

      {canManage ? (
        <div className="flex justify-end">
          <button type="button" onClick={openCreate} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
            Crear disciplina
          </button>
        </div>
      ) : null}

      <section className="card-surface p-5">
        <DataTable columns={columns} data={disciplines} loading={loading} />
      </section>

      <FormModal open={creating} onClose={() => setCreating(false)} title="Nueva disciplina">
        <form onSubmit={submitCreate} className="space-y-3">
          <label className="space-y-1 text-sm block">
            <span>Nombre</span>
            <input
              required
              autoFocus
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="Ej: BJJ, Box, Muay Thai"
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm block">
            <span>Descripción <span className="text-brand-dim">(opcional)</span></span>
            <textarea
              rows={3}
              value={newDescription}
              onChange={(event) => setNewDescription(event.target.value)}
              placeholder="Detalle opcional de la disciplina"
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={newActive}
              onChange={(event) => setNewActive(event.target.checked)}
              className="h-4 w-4 rounded border-brand-line bg-black/30"
            />
            <span>Activo</span>
          </label>
          {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
          <div className="flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Crear
            </button>
          </div>
        </form>
      </FormModal>

      <FormModal open={Boolean(editing)} onClose={() => setEditing(null)} title="Editar disciplina">
        <form onSubmit={submitEdit} className="space-y-3">
          <label className="space-y-1 text-sm block">
            <span>Nombre</span>
            <input
              required
              value={editName}
              onChange={(event) => setEditName(event.target.value)}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm block">
            <span>Descripción <span className="text-brand-dim">(opcional)</span></span>
            <textarea
              rows={3}
              value={editDescription}
              onChange={(event) => setEditDescription(event.target.value)}
              placeholder="Detalle opcional de la disciplina"
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={editActive}
              onChange={(event) => setEditActive(event.target.checked)}
              className="h-4 w-4 rounded border-brand-line bg-black/30"
            />
            <span>Activo</span>
          </label>
          {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
          <div className="flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Guardar
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar disciplina"
        message={`Se eliminará ${deleting?.name || 'esta disciplina'}.`}
        confirmLabel="Eliminar"
        variant="danger"
        onCancel={() => setDeleting(null)}
        onConfirm={removeItem}
      />
    </div>
  )
}
