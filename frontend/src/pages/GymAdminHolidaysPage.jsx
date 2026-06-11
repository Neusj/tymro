import { useEffect, useMemo, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { branchesApi, holidaysApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { canManageOperational } from '../utils/roles'

const initialForm = {
  date: '',
  name: '',
  scope: 'organization',
  source_type: 'manual',
  branch: '',
  is_active: true,
}

export default function GymAdminHolidaysPage() {
  const { user } = useAuth()
  const canManage = canManageOperational(user?.role)
  const [form, setForm] = useState(initialForm)
  const [editingId, setEditingId] = useState(null)
  const [items, setItems] = useState([])
  const [branches, setBranches] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [selectedIds, setSelectedIds] = useState([])
  const [error, setError] = useState('')

  const loadData = async () => {
    setLoading(true)
    try {
      const [holidaysData, branchesData] = await Promise.all([holidaysApi.list({ ordering: 'date' }), branchesApi.list()])
      const sortedHolidays = holidaysData
      setItems(holidaysData)
      setBranches(branchesData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const payload = {
        ...form,
        branch: form.scope === 'branch' ? form.branch : null,
      }
      if (editingId) {
        await holidaysApi.update(editingId, payload)
      } else {
        await holidaysApi.create(payload)
      }
      setForm(initialForm)
      setEditingId(null)
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || Object.values(detail || {})?.[0]?.[0] || 'No se pudo guardar el festivo.')
    } finally {
      setSaving(false)
    }
  }

  const editItem = (row) => {
    setEditingId(row.id)
    setForm({
      date: row.date,
      name: row.name,
      scope: row.scope,
      source_type: row.source_type || 'manual',
      branch: row.branch || '',
      is_active: row.is_active,
    })
    setError('')
  }

  const removeItem = async (row) => {
    const confirmed = window.confirm(`Eliminar festivo ${row.name}?`)
    if (!confirmed) {
      return
    }
    setError('')
    try {
      await holidaysApi.remove(row.id)
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudo eliminar el festivo.')
    }
  }

  const columns = useMemo(
    () => [
      { key: 'date', label: 'Fecha' },
      { key: 'name', label: 'Nombre' },
      { key: 'source_type', label: 'Origen', render: (row) => (row.source_type === 'system' ? 'Sistema base' : 'Manual') },
      { key: 'scope', label: 'Ambito', render: (row) => (row.scope === 'global' ? 'Global' : row.scope === 'branch' ? 'Sucursal' : 'Organizacion') },
      { key: 'branch_name', label: 'Sucursal', render: (row) => row.branch_name || '-' },
      { key: 'is_active', label: 'Estado', render: (row) => <ValueBadge kind="template_status" value={row.is_active ? 'active' : 'inactive'} /> },
      ...(canManage
        ? [
            {
              key: 'actions',
              label: 'Acciones',
              render: (row) => (
                <>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await holidaysApi.update(row.id, { is_active: !row.is_active })
                        await loadData()
                      } catch (apiError) {
                        const detail = apiError?.response?.data
                        setError(detail?.detail || 'No se pudo actualizar estado del festivo.')
                      }
                    }}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white"
                  >
                    {row.is_active ? 'Desactivar' : 'Activar'}
                  </button>
                  <button type="button" onClick={() => editItem(row)} className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white">
                    Editar
                  </button>
                  <button type="button" onClick={() => removeItem(row)} className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200">
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
      <DashboardHeader title="Gym Admin · Festivos" subtitle="Los festivos activos bloquean generacion de clases. Puedes gestionar base del sistema y excepciones manuales." back={{ to: '/gym-admin/classes', label: 'Clases' }} />

      {canManage ? (
      <section className="card-surface p-5">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span>Fecha</span>
            <input required type="date" value={form.date} onChange={(event) => setForm((prev) => ({ ...prev, date: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Nombre</span>
            <input required value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Ambito</span>
            <select value={form.scope} onChange={(event) => setForm((prev) => ({ ...prev, scope: event.target.value, branch: '' }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
              <option value="organization">Organizacion</option>
              <option value="branch">Sucursal</option>
            </select>
          </label>
          <p className="rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-xs text-brand-muted">
            Los festivos creados aqui son manuales. Los festivos de sistema se administran desde configuracion base.
          </p>
          {form.scope === 'branch' ? (
            <label className="space-y-1 text-sm">
              <span>Sucursal</span>
              <select required value={form.branch} onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2">
                <option value="">Seleccionar</option>
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="md:col-span-2 flex justify-end gap-2">
            {editingId ? (
              <button type="button" onClick={() => { setEditingId(null); setForm(initialForm) }} className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white">
                Cancelar
              </button>
            ) : null}
            <button type="submit" disabled={saving} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {saving ? 'Guardando...' : editingId ? 'Guardar cambios' : 'Crear festivo'}
            </button>
          </div>
        </form>
        {error ? <p className="mt-3 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      </section>
      ) : null}

      <section className="card-surface p-5">
        <p className="mb-3 text-sm text-brand-muted">Seleccionados en pagina actual: {selectedIds.length}</p>
        <DataTable
          columns={columns}
          data={items}
          loading={loading}
          selectableRows
          selectedRowIds={selectedIds}
          onSelectedRowIdsChange={setSelectedIds}
          defaultSort={{ key: 'date', direction: 'asc' }}
        />
      </section>
    </div>
  )
}

