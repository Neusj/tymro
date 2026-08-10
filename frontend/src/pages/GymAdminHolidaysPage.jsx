import { useEffect, useMemo, useRef, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import ConfirmDialog from '../components/ConfirmDialog'
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
  const [deletingHoliday, setDeletingHoliday] = useState(null)
  const formSectionRef = useRef(null)
  const firstFieldRef = useRef(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const [holidaysData, branchesData] = await Promise.all([holidaysApi.list({ ordering: 'date' }), branchesApi.list()])
      setItems(holidaysData)
      setBranches(branchesData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const resetForm = () => {
    setForm(initialForm)
    setEditingId(null)
  }

  const focusForm = () => {
    window.setTimeout(() => {
      formSectionRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
      firstFieldRef.current?.focus?.({ preventScroll: true })
    }, 0)
  }

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
      resetForm()
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
    focusForm()
  }

  const removeItem = async () => {
    if (!deletingHoliday?.id) {
      return
    }
    setError('')
    try {
      await holidaysApi.remove(deletingHoliday.id)
      setDeletingHoliday(null)
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
                  <button type="button" onClick={() => setDeletingHoliday(row)} className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200">
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
        <section ref={formSectionRef} className="card-surface p-5">
          <h2 className="panel-title mb-4">{editingId ? 'Editar festivo' : 'Crear festivo'}</h2>
          {editingId ? (
            <p className="mb-4 rounded-lg border border-brand-orange/40 bg-brand-orange/10 px-3 py-2 text-sm text-brand-white">
              Editando festivo #{editingId}. Guarda cambios o cancela para volver a crear.
            </p>
          ) : null}
          <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span>Fecha</span>
              <input ref={firstFieldRef} required type="date" value={form.date} onChange={(event) => setForm((prev) => ({ ...prev, date: event.target.value }))} className="field" />
            </label>
            <label className="space-y-1 text-sm">
              <span>Nombre</span>
              <input required value={form.name} onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))} className="field" />
            </label>
            <label className="space-y-1 text-sm">
              <span>Ambito</span>
              <select value={form.scope} onChange={(event) => setForm((prev) => ({ ...prev, scope: event.target.value, branch: '' }))} className="field">
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
                <select required value={form.branch} onChange={(event) => setForm((prev) => ({ ...prev, branch: event.target.value }))} className="field">
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
                <button type="button" onClick={resetForm} className="btn-ghost">
                  Cancelar
                </button>
              ) : null}
              <button type="submit" disabled={saving} className="btn-primary">
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

      <ConfirmDialog
        open={Boolean(deletingHoliday)}
        title="Eliminar festivo"
        description={`Eliminar festivo ${deletingHoliday?.name || ''}?`}
        confirmLabel="Eliminar"
        onConfirm={removeItem}
        onCancel={() => setDeletingHoliday(null)}
      />
    </div>
  )
}
