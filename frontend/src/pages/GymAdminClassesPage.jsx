import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { classesApi, disciplinesApi } from '../api/client'
import BulkActionModal from '../components/BulkActionModal'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FilterDropdown from '../components/FilterDropdown'
import FilterPanel from '../components/FilterPanel'
import KpiStrip from '../components/KpiStrip'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

const STATUS_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'scheduled', label: 'Programada' },
  { value: 'in_progress', label: 'En curso' },
  { value: 'completed', label: 'Finalizada' },
  { value: 'completed_early', label: 'Finalizada anticipadamente' },
  { value: 'cancelled', label: 'Cancelada' },
]

export default function GymAdminClassesPage() {
  const [classes, setClasses] = useState([])
  const [summary, setSummary] = useState(null)
  const [disciplines, setDisciplines] = useState([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [activeStatus, setActiveStatus] = useState('')
  const [activeDiscipline, setActiveDiscipline] = useState('')

  const disciplineOptions = useMemo(
    () => [
      { value: '', label: 'Todas' },
      ...disciplines.map((item) => ({ value: item.name, label: item.name })),
    ],
    [disciplines],
  )

  const filtersParams = useMemo(() => {
    const params = { ordering: 'start_datetime' }
    if (activeStatus) {
      params.status = activeStatus
    }
    if (activeDiscipline) {
      params.discipline = activeDiscipline
    }
    return params
  }, [activeStatus, activeDiscipline])

  const loadData = async () => {
    setLoading(true)
    try {
      const [classesData, summaryData, disciplinesData] = await Promise.all([
        classesApi.list(filtersParams),
        classesApi.dashboardSummary(filtersParams),
        disciplinesApi.list(),
      ])
      setClasses(classesData)
      setSummary(summaryData)
      setDisciplines(disciplinesData)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [filtersParams])

  const removeClass = async () => {
    if (!deleting) {
      return
    }
    await classesApi.remove(deleting.id)
    setDeleting(null)
    await loadData()
  }

  const runBulkAction = async ({ action, comment }) => {
    setError('')
    if (selectedIds.length === 0) {
      setError('Selecciona al menos una clase del conjunto filtrado.')
      return
    }
    setWorking(true)
    try {
      await classesApi.bulkClose({
        class_ids: selectedIds,
        action,
        comment,
      })
      setSelectedIds([])
      setBulkModalOpen(false)
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudo ejecutar la accion masiva.')
    } finally {
      setWorking(false)
    }
  }

  const closeSingleClass = async (gymClass, actionName) => {
    const comment = window.prompt(actionName === 'cancel' ? 'Motivo de cancelacion' : 'Motivo de cierre anticipado')
    if (!comment || !comment.trim()) {
      return
    }

    setError('')
    setWorking(true)
    try {
      if (actionName === 'cancel') {
        await classesApi.cancel(gymClass.id, comment.trim())
      } else {
        await classesApi.completeEarly(gymClass.id, comment.trim())
      }
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudo actualizar la clase.')
    } finally {
      setWorking(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'name', label: 'Clase' },
      { key: 'branch_name', label: 'Sucursal' },
      { key: 'teacher_name', label: 'Profesor' },
      { key: 'class_type_name', label: 'Tipo', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      { key: 'class_template_name', label: 'Serie', render: (row) => row.class_template_name || '-' },
      { key: 'start_datetime', label: 'Inicio', render: (row) => formatDateTime(row.start_datetime) },
      { key: 'end_datetime', label: 'Termino', render: (row) => formatDateTime(row.end_datetime) },
      {
        key: 'capacity',
        label: 'Cupos',
        sortAccessor: (row) => row.capacity,
        render: (row) => `${row.enrollments_count || 0}/${row.capacity}`,
      },
      { key: 'status', label: 'Estado', render: (row) => <ValueBadge kind="class_status" value={row.status} /> },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => {
          const canClose = !['completed', 'cancelled', 'completed_early'].includes(row.status)
          return (
            <>
              <Link
                to={`/gym-admin/classes/${row.id}`}
                className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
              >
                Detalle
              </Link>
              <Link
                to={`/gym-admin/classes/${row.id}/edit`}
                className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
              >
                Editar
              </Link>
              <button
                type="button"
                disabled={!canClose || working}
                onClick={() => closeSingleClass(row, 'complete_early')}
                className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
              >
                Cerrar anticipadamente
              </button>
              <button
                type="button"
                disabled={!canClose || working}
                onClick={() => closeSingleClass(row, 'cancel')}
                className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => setDeleting(row)}
                className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10"
              >
                Eliminar
              </button>
            </>
          )
        },
      },
    ],
    [working],
  )

  const totals = summary?.totals || {}

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Clases"
        subtitle="Gestion operativa de clases con filtros, KPIs y acciones seguras."
        extra={
          <Link to="/gym-admin/classes/create" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
            Crear clase
          </Link>
        }
      />

      <section className="card-surface p-5 space-y-4">
        <h2 className="panel-title hidden md:block">Resumen</h2>
        <KpiStrip
          items={[
            { label: 'Total clases', value: totals.total_classes || 0 },
            { label: 'Inscritos', value: totals.total_active_enrollments || 0 },
            { label: 'Ocupacion promedio', value: `${totals.occupancy_percent || 0}%` },
          ]}
        />

        <FilterPanel
          activeCount={(activeStatus ? 1 : 0) + (activeDiscipline ? 1 : 0)}
          onClear={() => {
            setActiveStatus('')
            setActiveDiscipline('')
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <FilterDropdown label="Estado" value={activeStatus} options={STATUS_OPTIONS} onChange={setActiveStatus} />
            <FilterDropdown label="Disciplina" value={activeDiscipline} options={disciplineOptions} onChange={setActiveDiscipline} />
          </div>
        </FilterPanel>
      </section>

      <section className="card-surface p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="panel-title">Detalle de clases (filtrado)</h2>
          <button
            type="button"
            disabled={!selectedIds.length}
            onClick={() => setBulkModalOpen(true)}
            className="rounded-lg border border-brand-orange px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-50"
          >
            Acciones masivas ({selectedIds.length})
          </button>
        </div>
        {error ? <p className="mb-3 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
        <DataTable
          columns={columns}
          data={classes}
          loading={loading}
          selectableRows
          selectAllScope="filtered"
          selectedRowIds={selectedIds}
          onSelectedRowIdsChange={setSelectedIds}
          defaultSort={{ key: 'start_datetime', direction: 'asc' }}
        />
      </section>

      <BulkActionModal
        open={bulkModalOpen}
        title="Acciones masivas de clases"
        selectedCount={selectedIds.length}
        loading={working}
        actions={[
          {
            value: 'complete_early',
            label: 'Cerrar anticipadamente clases',
            description: 'Cierra las clases seleccionadas sin borrar historico.',
          },
          {
            value: 'cancel',
            label: 'Cancelar clases',
            description: 'Cancela clases futuras seleccionadas y preserva trazabilidad.',
          },
        ]}
        requiresCommentActions={['complete_early', 'cancel']}
        defaultAction="cancel"
        onClose={() => setBulkModalOpen(false)}
        onConfirm={runBulkAction}
      />

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar clase"
        description={`Se eliminara ${deleting?.name || 'esta clase'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeClass}
      />
    </div>
  )
}
