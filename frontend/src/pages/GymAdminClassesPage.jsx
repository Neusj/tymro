import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { advanceClassWindowsApi, classesApi, disciplinesApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { canManageOperational } from '../utils/roles'
import BulkActionModal from '../components/BulkActionModal'
import ClassEnrollmentModal from '../components/ClassEnrollmentModal'
import ConfirmDialog from '../components/ConfirmDialog'
import ConfirmWithReasonDialog from '../components/ConfirmWithReasonDialog'
import DashboardHeader from '../components/DashboardHeader'
import DaySelector, { todayIsoDate } from '../components/DaySelector'
import FilterDropdown from '../components/FilterDropdown'
import FilterPanel from '../components/FilterPanel'
import KpiStrip from '../components/KpiStrip'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { sortClassesByStartTime } from './teacherClasses.helpers'

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function formatTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleTimeString('es-CL', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatTimeRange(start, end) {
  if (!start) {
    return '-'
  }
  return end ? `${formatTime(start)} - ${formatTime(end)}` : formatTime(start)
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

function canManageEnrollments(row) {
  return !isVirtualClass(row) && row?.status !== 'cancelled'
}

export default function GymAdminClassesPage({ embedded = false, onOpenSchedule } = {}) {
  const location = useLocation()
  const { user } = useAuth()
  const initialClassListState = location.state?.classListState || {}
  const canManage = canManageOperational(user?.role)
  const canUpdateGeneratedClasses = user?.role === 'gym_admin'
  const [classes, setClasses] = useState([])
  const [selectedDate, setSelectedDate] = useState(() => initialClassListState.selectedDate || todayIsoDate())
  const [disciplines, setDisciplines] = useState([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(null)
  const [singleAction, setSingleAction] = useState(null)
  const [reactivating, setReactivating] = useState(null)
  const [enrollmentClass, setEnrollmentClass] = useState(null)
  const [enrollmentInitialView, setEnrollmentInitialView] = useState('enroll')
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [activeStatus, setActiveStatus] = useState(() => initialClassListState.activeStatus || '')
  const [activeDiscipline, setActiveDiscipline] = useState(() => initialClassListState.activeDiscipline || '')
  const [activeSubstitute, setActiveSubstitute] = useState(() => initialClassListState.activeSubstitute || '')

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

  const displayedClasses = useMemo(() => sortClassesByStartTime(classes), [classes])
  const projectedCount = useMemo(
    () => displayedClasses.filter((item) => isVirtualClass(item)).length,
    [displayedClasses],
  )
  const classListRouteState = useMemo(() => ({
    classListState: { selectedDate, activeStatus, activeDiscipline, activeSubstitute },
    classListBackTo: { pathname: location.pathname, search: location.search },
  }), [activeDiscipline, activeStatus, activeSubstitute, location.pathname, location.search, selectedDate])

  useEffect(() => {
    const visibleIds = new Set(displayedClasses.map((item) => item.id))
    setSelectedIds((prev) => prev.filter((id) => visibleIds.has(id)))
  }, [displayedClasses])

  const removeClass = async () => {
    if (!deleting) {
      return
    }
    setError('')
    setNotice('')
    setWorking(true)
    try {
      await classesApi.remove(deleting.id)
      setNotice('Registro eliminado.')
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudo eliminar el registro de la clase.')
    } finally {
      setWorking(false)
    }
  }

  const updateGeneratedClasses = async () => {
    setError('')
    setNotice('')
    setWorking(true)
    try {
      const summary = await advanceClassWindowsApi.run()
      const created = Number(summary?.instances_created || 0)
      setNotice(
        created > 0
          ? `Se generaron ${created} clases reales.`
          : 'Calendario actualizado. No habia clases nuevas por generar.',
      )
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudo actualizar el calendario de clases.')
    } finally {
      setWorking(false)
    }
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

  const openEnrollmentModal = (gymClass, initialView = 'enroll') => {
    if (!canManageEnrollments(gymClass)) {
      setError('No puedes modificar inscripciones en una clase cancelada o proyectada.')
      return
    }
    setError('')
    setEnrollmentClass(gymClass)
    setEnrollmentInitialView(initialView)
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

  const reactivateClass = async () => {
    if (!reactivating?.id) {
      return
    }

    setError('')
    setWorking(true)
    try {
      await classesApi.reactivate(reactivating.id)
      setReactivating(null)
      await loadData()
    } catch (apiError) {
      const detail = apiError?.response?.data
      setError(detail?.detail || 'No se pudo reabrir la clase.')
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
        mobile: 'hidden',
        render: (row) => (row.has_substitute ? row.substitute_display_name || row.substitute_name || '-' : <span className="text-brand-muted">Sin suplente</span>),
      },
      { key: 'class_type_name', label: 'Tipo', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'discipline_name', label: 'Disciplina', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      // TODO unificacion: esta columna sigue diciendo "Serie" (jerga vieja) porque renombrarla a
      // "Clase" chocaria con la columna del nombre de la clase, dos lineas mas arriba. Se resuelve
      // en el rediseno junto con la fusion de la pantalla puntual y la de series.
      { key: 'class_template_name', label: 'Serie', render: (row) => row.class_template_name || '-' },
      {
        key: 'start_datetime',
        label: 'Inicio',
        mobile: 'secondary',
        mobileLabel: 'Hora',
        mobilePriority: 3,
        render: (row) => formatDateTime(row.start_datetime),
        mobileRender: (row) => formatTimeRange(row.start_datetime, row.end_datetime),
      },
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
        hideActionsInDetail: true,
        mobilePrimaryReplacesDetail: true,
        mobilePrimary: (row) =>
          isVirtualClass(row) ? (
            <button
              type="button"
              disabled={working || !canUpdateGeneratedClasses}
              onClick={updateGeneratedClasses}
              className="rounded-lg border border-brand-orange/60 px-3 py-2 text-center text-xs font-semibold text-brand-white transition hover:border-brand-orange disabled:opacity-60"
            >
              Generar clase real
            </button>
          ) : (
            <Link
              to={`/gym-admin/classes/${row.id}/attendance`}
              state={classListRouteState}
              className="block rounded-lg border border-brand-blue/70 bg-brand-blue/15 px-3 py-2 text-center text-xs font-semibold text-brand-white transition hover:border-brand-blue"
            >
              Asistencia
            </Link>
          ),
        mobileActionsRender: (row) => {
          const canClose = !['completed', 'cancelled', 'completed_early'].includes(row.status)
          const canReopen = row.status === 'cancelled'
          const isVirtual = isVirtualClass(row)
          const enrollmentDisabled = !canManageEnrollments(row)
          const canDeleteRecord = !row.class_template
          if (isVirtual) {
            return (
              <>
                <p className="rounded-lg border border-brand-line bg-black/20 px-2.5 py-2 text-xs text-brand-muted">
                  Clase proyectada. Genera el calendario para operar asistencia, inscritos o cancelacion.
                </p>
                {canUpdateGeneratedClasses ? (
                  <button
                    type="button"
                    disabled={working}
                    onClick={updateGeneratedClasses}
                    className="w-full rounded-lg border border-brand-orange/60 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
                  >
                    Generar clases reales
                  </button>
                ) : null}
              </>
            )
          }
          return canManage ? (
            <>
              <button
                type="button"
                disabled={!canClose || working}
                onClick={() => requestCloseSingleClass(row, 'cancel')}
                className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
              >
                Cancelar clase
              </button>
              <button
                type="button"
                disabled={enrollmentDisabled || working}
                onClick={() => openEnrollmentModal(row, 'enroll')}
                className="w-full rounded-lg border border-brand-blue/60 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
              >
                Inscribir alumnos
              </button>
              <button
                type="button"
                disabled={enrollmentDisabled || working}
                onClick={() => openEnrollmentModal(row, 'enrolled')}
                className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
              >
                Ver inscritos
              </button>
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
                  state={classListRouteState}
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
              {canReopen ? (
                <button
                  type="button"
                  disabled={working || isVirtual}
                  onClick={() => setReactivating(row)}
                  className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                >
                  Reabrir clase
                </button>
              ) : null}
              {canDeleteRecord ? (
                <button
                  type="button"
                  onClick={() => setDeleting(row)}
                  className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                >
                  Eliminar registro
                </button>
              ) : null}
            </>
          ) : null
        },
        render: (row) => {
          const canClose = !['completed', 'cancelled', 'completed_early'].includes(row.status)
          const canReopen = row.status === 'cancelled'
          const isVirtual = isVirtualClass(row)
          const enrollmentDisabled = !canManageEnrollments(row)
          const canDeleteRecord = !row.class_template
          if (isVirtual) {
            return (
              <>
                <p className="rounded-lg border border-brand-line bg-black/20 px-2.5 py-2 text-xs text-brand-muted">
                  Clase proyectada. Todavia no existe como instancia real.
                </p>
                {canUpdateGeneratedClasses ? (
                  <button
                    type="button"
                    disabled={working}
                    onClick={updateGeneratedClasses}
                    className="w-full rounded-lg border border-brand-orange/60 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-orange disabled:opacity-60"
                  >
                    Generar clases reales
                  </button>
                ) : null}
              </>
            )
          }
          return (
            <>
              <Link
                to={`/gym-admin/classes/${row.id}`}
                state={classListRouteState}
                className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue"
              >
                Detalle
              </Link>
              {canManage ? (
                <>
                  <button
                    type="button"
                    disabled={!canClose || working}
                    onClick={() => requestCloseSingleClass(row, 'cancel')}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                  >
                    Cancelar clase
                  </button>
                  <button
                    type="button"
                    disabled={enrollmentDisabled || working}
                    onClick={() => openEnrollmentModal(row, 'enroll')}
                    className="w-full rounded-lg border border-brand-blue/60 px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Inscribir alumnos
                  </button>
                  <button
                    type="button"
                    disabled={enrollmentDisabled || working}
                    onClick={() => openEnrollmentModal(row, 'enrolled')}
                    className="w-full rounded-lg border border-brand-line px-2.5 py-1.5 text-left text-xs text-brand-white transition hover:border-brand-blue disabled:opacity-60"
                  >
                    Ver inscritos
                  </button>
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
                      state={classListRouteState}
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
                  {canReopen ? (
                    <button
                      type="button"
                      disabled={working || isVirtual}
                      onClick={() => setReactivating(row)}
                      className="w-full rounded-lg border border-emerald-500/50 px-2.5 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-400 disabled:opacity-60"
                    >
                      Reabrir clase
                    </button>
                  ) : null}
                  {canDeleteRecord ? (
                    <button
                      type="button"
                      onClick={() => setDeleting(row)}
                      className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 transition hover:bg-brand-red/10 disabled:opacity-60"
                    >
                      Eliminar registro
                    </button>
                  ) : null}
                </>
              ) : null}
            </>
          )
        },
      },
    ],
    [classListRouteState, working, canManage, canUpdateGeneratedClasses],
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
      {!embedded ? (
      <DashboardHeader
        title="Gym Admin · Clases generadas"
        subtitle="Revisión operativa de instancias, asistencia, inscritos y acciones administrativas."
        extra={
          canManage ? (
            <Link to="/gym-admin/class-templates" className="btn-primary">
              Gestión de clases
            </Link>
          ) : null
        }
      />
      ) : null}

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

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="panel-title">Detalle de clases (filtrado)</h2>
          {canManage ? (
            <div className="flex flex-wrap justify-end gap-2">
              {onOpenSchedule ? (
                <button
                  type="button"
                  onClick={onOpenSchedule}
                  className="btn-ghost text-xs"
                >
                  Ver programacion
                </button>
              ) : null}
              {canUpdateGeneratedClasses && projectedCount > 0 ? (
                <button
                  type="button"
                  disabled={working}
                  onClick={updateGeneratedClasses}
                  className="btn-primary text-xs"
                >
                  Generar clases reales ({projectedCount})
                </button>
              ) : null}
              <button
                type="button"
                disabled={!selectedIds.length}
                onClick={() => setBulkModalOpen(true)}
                className="btn-ghost text-xs"
              >
                Acciones masivas ({selectedIds.length})
              </button>
            </div>
          ) : null}
        </div>
        {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
        {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}
        <DataTable
          columns={columns}
          data={displayedClasses}
          loading={loading}
          selectableRows={canManage}
          selectAllScope="filtered"
          selectedRowIds={selectedIds}
          onSelectedRowIdsChange={setSelectedIds}
          disablePagination
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
        title="Eliminar registro de clase"
        description={`Se borrara ${deleting?.name || 'esta clase'} del sistema. Para conservar historial operativo normalmente conviene Cancelar, no eliminar.`}
        confirmLabel="Eliminar registro"
        loading={working}
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

      <ConfirmDialog
        open={Boolean(reactivating)}
        title="Reabrir clase"
        description={`Se reabrira ${reactivating?.name || 'esta clase'}. Las reservas canceladas no se restauraran automaticamente; los alumnos deberan volver a inscribirse o reservar si tienen cupos disponibles.`}
        confirmLabel="Reabrir clase"
        variant="default"
        loading={working}
        onCancel={() => {
          if (!working) {
            setReactivating(null)
          }
        }}
        onConfirm={reactivateClass}
      />

      <ClassEnrollmentModal
        open={Boolean(enrollmentClass)}
        gymClass={enrollmentClass}
        initialView={enrollmentInitialView}
        onClose={() => setEnrollmentClass(null)}
        onChanged={loadData}
      />
    </div>
  )
}
