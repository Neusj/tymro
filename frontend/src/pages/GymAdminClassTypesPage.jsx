import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { classTypesApi } from '../api/client'
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

export default function GymAdminClassTypesPage() {
  const [classTypes, setClassTypes] = useState([])
  const [loading, setLoading] = useState(true)
  const [newTypeName, setNewTypeName] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [editName, setEditName] = useState('')
  const [deleting, setDeleting] = useState(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const data = await classTypesApi.list()
      setClassTypes(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const createType = async () => {
    const name = newTypeName.trim()
    if (!name) {
      return
    }
    setError('')
    try {
      const created = await classTypesApi.create({ name })
      setClassTypes((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)))
      setNewTypeName('')
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo crear el tipo de clase.'))
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
      await classTypesApi.update(editing.id, { name: editName })
      setEditing(null)
      setEditName('')
      await loadData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo editar el tipo de clase.'))
    }
  }

  const removeType = async () => {
    if (!deleting) {
      return
    }
    setError('')
    try {
      await classTypesApi.remove(deleting.id)
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo eliminar el tipo de clase.'))
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
    ],
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Tipos de Clase"
        subtitle="Gestiona tipos de clase de tu organización."
        extra={
          <Link to="/gym-admin/classes" className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-muted">
            Volver a clases
          </Link>
        }
      />

      <section className="card-surface p-5 space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={newTypeName}
            onChange={(event) => setNewTypeName(event.target.value)}
            placeholder="Ej: Grupal, Privada"
            className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
          />
          <button type="button" onClick={createType} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
            Crear
          </button>
        </div>
        {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={classTypes} loading={loading} />
      </section>

      <FormModal open={Boolean(editing)} onClose={() => setEditing(null)} title="Editar tipo de clase">
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
        title="Eliminar tipo"
        description={`Se eliminará ${deleting?.name || 'este tipo de clase'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeType}
      />
    </div>
  )
}
