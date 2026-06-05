import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { disciplinesApi } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import DataTable from '../components/ui/DataTable'

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
  const [disciplines, setDisciplines] = useState([])
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [editName, setEditName] = useState('')
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

  const createItem = async () => {
    const name = newName.trim()
    if (!name) {
      return
    }
    setError('')
    try {
      const created = await disciplinesApi.create({ name })
      setDisciplines((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setNewName('')
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo crear la disciplina.'))
    }
  }

  const openEdit = (item) => {
    setEditing(item)
    setEditName(item.name || '')
    setError('')
  }

  const submitEdit = async (event) => {
    event.preventDefault()
    if (!editing) {
      return
    }

    setError('')
    try {
      await disciplinesApi.update(editing.id, { name: editName })
      setEditing(null)
      setEditName('')
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
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Disciplinas"
        subtitle="Gestiona disciplinas como BJJ, Box, etc. para métricas futuras."
        extra={
          <Link to="/gym-admin/classes" className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-muted">
            Volver a clases
          </Link>
        }
      />

      <section className="card-surface p-5 space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder="Ej: BJJ, Box, Muay Thai"
            className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
          />
          <button type="button" onClick={createItem} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
            Crear
          </button>
        </div>
        {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={disciplines} loading={loading} />
      </section>

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
        description={`Se eliminará ${deleting?.name || 'esta disciplina'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeItem}
      />
    </div>
  )
}
