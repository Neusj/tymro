import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { classesApi, disciplinesApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { canManageOperational } from '../utils/roles'
import BulkActionModal from '../components/BulkActionModal'
import ConfirmDialog from '../components/ConfirmDialog'
import ConfirmWithReasonDialog from '../components/ConfirmWithReasonDialog'
import DashboardHeader from '../components/DashboardHeader'
import DaySelector, { todayIsoDate } from '../components/DaySelector'
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

const SUBSTITUTE_OPTIONS = [
  { value: '', label: 'Todas' },
  { value: 'true', label: 'Con suplente' },
  { value: 'false', label: 'Sin suplente' },
]

function isVirtualClass(row) {
  return String(row?.id || '').startsWith('virtual:')
}

export default function GymAdminClassesPage() {
  const { user } = useAuth()
  const canManage = canManageOperational(user?.role)
  const [classes, setClasses] = useState([])
  const [selectedDate, setSelectedDate] = useState(todayIsoDate())
  const [disciplines, setDisciplines] = useState([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(null)
  const [singleAction, setSingleAction] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [activeStatus, setActiveStatus] = useState('')
  const [activeDiscipline, setActiveDiscipline] = useState('')
  const [activeSubstitute, setActiveSubstitute] = useState('')

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
    if (activeSubstitute) {
      params.has_substitute = activeSubstitute
    }
    return params
  }, [activeStatus, activeDiscipline, activeSubstitute])

  const loadData = async () => {
    setLoading(true)
    try {
      const [classesData, disciplinesData] = await Promise.all([
        classesApi.byDate(selectedDate, filtersParams),
        disciplinesApi.list(),
      ])
      setClasses(classesData)
      setDisciplines(disciplinesData)
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudieron cargar las clases.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [filtersParams, selectedDate])

  useEffect(() => {
    const visibleIds = new Set(classes.map((item) => item.id))
    setSelectedIds((prev) => prev.filter((id) => visibleIds.has(id)))
  }, [classes])

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
    const persistedIds = selectedIds.filter((id) => !String(id).startsWith('virtual:'))
    if (persistedIds.length === 0) {
      setError('Las clases proyectadas se podran operar cuando exista la instancia.')
      return
    }
    setWorking(true)
    try {
      await classesApi.bulkClose({
        class_ids: persistedIds,
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

  const requestCloseSingleClass = (gymClass, actionName) => {
    if (isVirtualClass(gymClass)) {
      setError('Las clases proyectadas se podran operar cuando exista la instancia.')
      return
    }
    setSingleAction({ gymClass, actionName })
  }

  const closeSingleClass = async (comment) => {
    if (!singleAction?.gymClass || !comment?.trim()) {
      return
    }

    const { gymClass, actionName } = singleAction
    setError('')
    setWorking(true)
    try {
      if (actionName === 'cancel') {
        await classesApi.cancel(gymClass.id, comment.trim())
      } else {
        await classesApi.completeEarly(gymClass.id, comment.trim())
      }
      setSingleAction(null)
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
      {
        key: 'substitute_display_name',
        label: 'Suplente',
        mobile: 'secondary',
        render: (row) => (row.has_substitute ? row.substitute_display_name || row.substitute_name || '-' : <span className="text-brand-muted">Sin suplente</span>),
      },
      { key: 'class_type_name', label: 'Tipo', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      // TODO unificacion: esta columna sigue diciendo "Serie" (jerga vieja) porque renombrarla a
      // "Clase" chocaria con la columna del nombre de la clase, dos lineas mas arriba. Se resuelve
      // en el rediseno junto con la fusion de la pantalla puntual y la de series.
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
          const isVirtual = isVirtualClass(row)
          return (
            <>
              {isVirtual ? (
                <button
                  type="button"
                  disabled
                  className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white opacity-60"
                >
                  Detalle
                </button>
              ) : (
                <Link
                  to={`/gym-admin/classes/${row.id}`}
                  className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
                >
                  Detalle
                </Link>
              )}
              {canManage ? (
                <>
                  {isVirtual ? (
                    <button
                      type="button"
                      disabled
                      className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white opacity-60"
                    >
                      Editar
                    </button>
                  ) : (
                    <Link
                      to={`/gym-admin/classes/${row.id}/edit`}
                      className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
                    >
                      Editar
                    </Link>
                  )}
                  <button
                    type="button"
                    disabled={!canClose || working || isVirtual}
                    onClick={() => requestCloseSingleClass(row, 'complete_early')}
                    className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
                  >
                    Cerrar anticipadamente
                  </button>
                  <button
                    type="button"
                    disabled={!canClose || working || isVirtual}
                    onClick={() => requestCloseSingleClass(row, 'cancel')}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar
                  </button>
                  <button
                    type="button"
                    disabled={isVirtual}
                    onClick={() => setDeleting(row)}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Eliminar
                  </button>
                </>
              ) : null}
            </>
          )
        },
      },
    ],
    [working, canManage],
  )

  const totals = useMemo(() => {
    const totalClasses = classes.length
    const totalActiveEnrollments = classes.reduce((sum, item) => sum + Number(item.enrollments_count || 0), 0)
    const totalCapacity = classes.reduce((sum, item) => sum + Number(item.capacity || 0), 0)
    return {
      total_classes: totalClasses,
      total_active_enrollments: totalActiveEnrollments,
      occupancy_percent: totalCapacity > 0 ? Math.round((totalActiveEnrollments / totalCapacity) * 100) : 0,
    }
  }, [classes])

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Clases"
        subtitle="Gestion operativa de clases con filtros, KPIs y acciones seguras."
        extra={
          canManage ? (
            // TODO unificacion: desvio temporal. "Crear clase" ahora lleva a la pantalla de series
            // recurrentes (/gym-admin/class-templates), que es la unica que soporta multi-dia. La
            // pantalla puntual (/gym-admin/classes/create) queda inerte pero viva: se decide en el
            // rediseno si se elimina o se fusiona con la de series.
            <Link to="/gym-admin/class-templates" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Crear clase
            </Link>
          ) : null
        }
      />

      <DaySelector value={selectedDate} onChange={setSelectedDate} />

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
          activeCount={(activeStatus ? 1 : 0) + (activeDiscipline ? 1 : 0) + (activeSubstitute ? 1 : 0)}
          onClear={() => {
            setActiveStatus('')
            setActiveDiscipline('')
            setActiveSubstitute('')
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <FilterDropdown label="Estado" value={activeStatus} options={STATUS_OPTIONS} onChange={setActiveStatus} />
            <FilterDropdown label="Disciplina" value={activeDiscipline} options={disciplineOptions} onChange={setActiveDiscipline} />
            <FilterDropdown label="Suplente" value={activeSubstitute} options={SUBSTITUTE_OPTIONS} onChange={setActiveSubstitute} />
          </div>
        </FilterPanel>
      </section>

      <section className="card-surface p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="panel-title">Detalle de clases (filtrado)</h2>
          {canManage ? (
            <button
              type="button"
              disabled={!selectedIds.length}
              onClick={() => setBulkModalOpen(true)}
              className="rounded-lg border border-brand-orange px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-50"
            >
              Acciones masivas ({selectedIds.length})
            </button>
          ) : null}
        </div>
        {error ? <p className="mb-3 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
        <DataTable
          columns={columns}
          data={classes}
          loading={loading}
          selectableRows={canManage}
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

      <ConfirmWithReasonDialog
        open={Boolean(singleAction)}
        title={singleAction?.actionName === 'cancel' ? 'Cancelar clase' : 'Cerrar anticipadamente'}
        description={`Se actualizara ${singleAction?.gymClass?.name || 'esta clase'} preservando trazabilidad.`}
        reasonLabel={singleAction?.actionName === 'cancel' ? 'Motivo de cancelacion' : 'Motivo de cierre anticipado'}
        confirmLabel={singleAction?.actionName === 'cancel' ? 'Cancelar clase' : 'Cerrar anticipadamente'}
        variant={singleAction?.actionName === 'cancel' ? 'danger' : 'warning'}
        loading={working}
        onCancel={() => {
          if (!working) {
            setSingleAction(null)
          }
        }}
        onConfirm={closeSingleClass}
      />
    </div>
  )
}
