import { useEffect, useMemo, useState } from 'react'
import { classTemplatesApi, classesApi, enrollmentsApi, getMyMemberships, recurringEnrollmentsApi } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import FilterDropdown from '../components/FilterDropdown'
import FilterPanel from '../components/FilterPanel'
import KpiStrip from '../components/KpiStrip'
import DataTable from '../components/ui/DataTable'
import TouchTooltip from '../components/ui/TouchTooltip'
import ValueBadge from '../components/ui/ValueBadge'
import {
  applyStudentClassFilters,
  applyStudentReservationFilters,
  calculateAvailableKpis,
  calculateReservationKpis,
  CLASS_STATUS_OPTIONS,
  extractStudentClassOptions,
  extractStudentReservationOptions,
  RESERVATION_MODE_OPTIONS,
  RESERVATION_STATUS_OPTIONS,
  formatDateTime,
} from './studentClasses.helpers'

const initialClassFilters = {
  teacher: '',
  discipline: '',
  status: '',
  dateRange: '',
}

// Clases disponibles: por defecto se acota a la semana actual (no un rango abierto
// que traería clases a meses/años vista). El historial NO usa este default: sus
// clases son pasadas y 'week' (hoy→+7) las ocultaría.
const initialAvailableClassFilters = {
  ...initialClassFilters,
  dateRange: 'week',
}

const initialReservationFilters = {
  teacher: '',
  discipline: '',
  status: 'active',
  classType: '',
  mode: '',
  dateRange: '',
}

function countActiveFilters(filters, initial) {
  return Object.keys(initial).reduce((count, key) => (filters[key] !== initial[key] ? count + 1 : count), 0)
}

function QuickChips({ items }) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          onClick={item.onClick}
          className={`shrink-0 rounded-full border px-3 py-2 text-xs font-semibold ${
            item.active ? 'border-brand-blue bg-brand-blue/20 text-brand-white' : 'border-brand-line text-brand-muted'
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

function firstApiError(detail, fallback) {
  if (!detail) {
    return fallback
  }
  if (typeof detail === 'string') {
    return detail
  }
  if (detail.detail) {
    return detail.detail
  }
  const firstValue = Object.values(detail)[0]
  if (Array.isArray(firstValue) && firstValue[0]) {
    return firstValue[0]
  }
  return fallback
}

export default function StudentClassesPage({ mode = 'available' }) {
  const [availableClasses, setAvailableClasses] = useState([])
  const [historyClasses, setHistoryClasses] = useState([])
  const [reservations, setReservations] = useState([])
  const [recurringItems, setRecurringItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [workingKey, setWorkingKey] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [memberships, setMemberships] = useState([])

  const [classFilters, setClassFilters] = useState(initialAvailableClassFilters)
  const [reservationFilters, setReservationFilters] = useState(initialReservationFilters)
  const [historyFilters, setHistoryFilters] = useState(initialClassFilters)
  const [selectedAvailableIds, setSelectedAvailableIds] = useState([])
  const [selectedReservationIds, setSelectedReservationIds] = useState([])
  // Clase pendiente de confirmar antes de reservar (#24). null = sin diálogo abierto.
  const [pendingReserve, setPendingReserve] = useState(null)
  // Rebook desde "Mis reservas" cuando hay 2+ planes usables: mismo diálogo de confirmación,
  // pero la clase-origen es una reserva cancelada, no una fila de "Clases disponibles".
  const [pendingRebook, setPendingRebook] = useState(null)
  // Bulk (#9 T4): con 2+ planes usables, el selector se abre UNA vez para todo el lote.
  const [pendingBulkReserve, setPendingBulkReserve] = useState(null)
  // Plan elegido en el selector del diálogo de confirmación (#9 T4). Se resetea al
  // abrir/cerrar cualquiera de los tres flujos de reserva.
  const [selectedPlanId, setSelectedPlanId] = useState('')

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [scheduledClasses, completedClasses, myReservations, myRecurring, myMemberships] = await Promise.allSettled([
        classesApi.list({ status_in: 'scheduled,in_progress,cancelled', ordering: 'start_datetime' }),
        classesApi.list({ mine: true, status_in: 'completed,completed_early', ordering: '-start_datetime' }),
        enrollmentsApi.my(),
        recurringEnrollmentsApi.my(),
        getMyMemberships(),
      ])
      if (scheduledClasses.status === 'fulfilled') {
        setAvailableClasses(scheduledClasses.value)
      }
      if (completedClasses.status === 'fulfilled') {
        setHistoryClasses(completedClasses.value)
      }
      if (myReservations.status === 'fulfilled') {
        setReservations(myReservations.value)
      }
      if (myRecurring.status === 'fulfilled') {
        setRecurringItems(myRecurring.value)
      }
      if (myMemberships.status === 'fulfilled') {
        setMemberships(Array.isArray(myMemberships.value) ? myMemberships.value : [])
      }

      const failed = [scheduledClasses, completedClasses, myReservations, myRecurring].find((result) => result.status === 'rejected')
      if (failed) {
        setError(firstApiError(failed.reason?.response?.data, 'No se pudo actualizar toda la informacion.'))
      }
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus clases.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const activeReservationByClass = useMemo(() => {
    const map = {}
    reservations.forEach((item) => {
      if (item.status === 'active') {
        map[item.gym_class] = item
      }
    })
    return map
  }, [reservations])

  const reservationByClass = useMemo(() => {
    const map = {}
    reservations.forEach((item) => {
      map[item.gym_class] = item
    })
    return map
  }, [reservations])

  const recurringById = useMemo(() => {
    const map = {}
    recurringItems.forEach((item) => {
      map[item.id] = item
    })
    return map
  }, [recurringItems])

  const recurringByTemplate = useMemo(() => {
    const map = {}
    recurringItems.forEach((item) => {
      if (!map[item.class_template]) {
        map[item.class_template] = item
      }
    })
    return map
  }, [recurringItems])

  const availableFilterOptions = useMemo(() => extractStudentClassOptions(availableClasses), [availableClasses])
  const reservationFilterOptions = useMemo(() => extractStudentReservationOptions(reservations), [reservations])
  const historyFilterOptions = useMemo(() => extractStudentClassOptions(historyClasses), [historyClasses])

  const filteredAvailable = useMemo(() => applyStudentClassFilters(availableClasses, classFilters), [availableClasses, classFilters])
  const filteredReservations = useMemo(() => applyStudentReservationFilters(reservations, reservationFilters), [reservations, reservationFilters])
  const filteredHistory = useMemo(() => applyStudentClassFilters(historyClasses, historyFilters), [historyClasses, historyFilters])
  const filteredAvailableForBooking = useMemo(
    () => filteredAvailable.filter((item) => !activeReservationByClass[item.id]),
    [activeReservationByClass, filteredAvailable],
  )

  const availableKpis = useMemo(
    () => calculateAvailableKpis(filteredAvailableForBooking, activeReservationByClass),
    [filteredAvailableForBooking, activeReservationByClass],
  )
  const reservationKpis = useMemo(() => calculateReservationKpis(filteredReservations), [filteredReservations])
  // Fuente única de saldo: `getMyMemberships` (no se deriva vigencia/saldo en el cliente).
  // `remaining_classes === null` = ilimitado, así que NUNCA entra en la suma de abajo.
  const usableMemberships = useMemo(
    () => memberships.filter((item) => item.remaining_classes === null || item.remaining_classes > 0),
    [memberships],
  )
  const hasPlanBalance = usableMemberships.length > 0
  const hasUnlimitedUsableMembership = usableMemberships.some((item) => item.remaining_classes === null)
  const totalRemainingClasses = usableMemberships.reduce((sum, item) => sum + (item.remaining_classes || 0), 0)
  const balanceChipLabel = hasUnlimitedUsableMembership ? 'Clases ilimitadas' : `${totalRemainingClasses} clases`
  // Regla del contrato (#9 T4): con 2+ planes usables, TODA creación de reserva debe
  // mandar student_plan_id (el alumno elige); con exactamente 1, se omite (lo resuelve
  // el backend); con 0 el bloqueo de siempre (hasPlanBalance) sigue vigente.
  const requiresPlanChoice = usableMemberships.length >= 2
  const resetPlanSelection = () => setSelectedPlanId('')

  useEffect(() => {
    setSelectedReservationIds((prev) => prev.filter((id) => filteredReservations.some((item) => item.id === id)))
  }, [filteredReservations])

  useEffect(() => {
    setSelectedAvailableIds((prev) => prev.filter((id) => filteredAvailableForBooking.some((item) => item.id === id)))
  }, [filteredAvailableForBooking])

  const reserveClass = async (gymClass, studentPlanId) => {
    if (!hasPlanBalance) {
      setError('Sin clases disponibles')
      return
    }
    setWorkingKey(`reserve-${gymClass.id}`)
    setError('')
    try {
      const payload = { gym_class: gymClass.id, status: 'active' }
      if (requiresPlanChoice) {
        payload.student_plan_id = Number(studentPlanId)
      }
      await enrollmentsApi.create(payload)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo reservar la clase.'))
    } finally {
      setWorkingKey('')
    }
  }

  // Abre el diálogo de confirmación (#24) para una reserva individual desde "Clases
  // disponibles". Siempre pasa por el diálogo; el selector de plan aparece adentro
  // solo si hay 2+ planes usables (requiresPlanChoice).
  const openSingleReserveConfirm = (row) => {
    resetPlanSelection()
    setPendingReserve(row)
  }

  // Confirma la reserva pendiente (#24): reserva y cierra el diálogo al terminar.
  const confirmPendingReserve = async () => {
    if (!pendingReserve) {
      return
    }
    const target = pendingReserve
    const planId = selectedPlanId
    await reserveClass(target, planId)
    setPendingReserve(null)
    resetPlanSelection()
  }

  const subscribeOrReactivateRecurring = async (gymClass) => {
    if (!gymClass.class_template) {
      return
    }
    const current = recurringByTemplate[gymClass.class_template]
    setWorkingKey(`recurring-${gymClass.id}`)
    setError('')
    try {
      if (current && !current.is_active) {
        await recurringEnrollmentsApi.update(current.id, { is_active: true })
      } else {
        await classTemplatesApi.recurringEnroll(gymClass.class_template, {
          start_date: String(gymClass.start_datetime || '').slice(0, 10),
          recurrence_type: 'weekly',
        })
      }
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo gestionar la recurrencia semanal.'))
    } finally {
      setWorkingKey('')
    }
  }

  const toggleRecurring = async (recurringEnrollment, nextState) => {
    setWorkingKey(`toggle-recurring-${recurringEnrollment.id}`)
    setError('')
    try {
      await recurringEnrollmentsApi.update(recurringEnrollment.id, { is_active: nextState })
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo actualizar la recurrencia.'))
    } finally {
      setWorkingKey('')
    }
  }

  const cancelReservation = async (reservation) => {
    setWorkingKey(`cancel-${reservation.id}`)
    setError('')
    setNotice('')
    try {
      await enrollmentsApi.cancel(reservation.id)
      await loadData()
      setNotice('Reserva cancelada correctamente.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cancelar la reserva.'))
    } finally {
      setWorkingKey('')
    }
  }

  const reserveFromReservation = async (reservation, studentPlanId) => {
    setWorkingKey(`reserve-reservation-${reservation.id}`)
    setError('')
    try {
      const payload = { gym_class: reservation.gym_class, status: 'active' }
      if (requiresPlanChoice) {
        payload.student_plan_id = Number(studentPlanId)
      }
      await enrollmentsApi.create(payload)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo reservar la clase.'))
    } finally {
      setWorkingKey('')
    }
  }

  // Rebook desde "Mis reservas": con 2+ planes usables hay que elegir, así que se
  // enruta por el mismo diálogo de confirmación (pendingRebook); con 0 o 1, se
  // mantiene el comportamiento directo de siempre (sin diálogo).
  const handleReserveFromReservationClick = (reservation) => {
    if (requiresPlanChoice) {
      resetPlanSelection()
      setPendingRebook(reservation)
      return
    }
    reserveFromReservation(reservation)
  }

  const confirmPendingRebook = async () => {
    if (!pendingRebook) {
      return
    }
    const target = pendingRebook
    const planId = selectedPlanId
    await reserveFromReservation(target, planId)
    setPendingRebook(null)
    resetPlanSelection()
  }

  const cancelSelectedReservations = async () => {
    const selectedRows = filteredReservations.filter((item) => selectedReservationIds.includes(item.id))
    const cancellable = selectedRows.filter((item) => item.status === 'active' && item.can_cancel)

    if (cancellable.length === 0) {
      setError('No hay reservas seleccionadas que se puedan cancelar.')
      return
    }

    setWorkingKey('cancel-bulk')
    setError('')
    setNotice('')
    try {
      const results = await Promise.allSettled(cancellable.map((item) => enrollmentsApi.cancel(item.id)))
      const successCount = results.filter((item) => item.status === 'fulfilled').length
      const failedCount = results.length - successCount
      await loadData()
      setSelectedReservationIds([])
      if (failedCount > 0) {
        setError(`Se cancelaron ${successCount} reservas y ${failedCount} fallaron.`)
      } else {
        setNotice(`Se cancelaron ${successCount} reservas correctamente.`)
      }
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cancelar las reservas seleccionadas.'))
    } finally {
      setWorkingKey('')
    }
  }

  // Ejecuta el batch de creates ya con el plan resuelto (o sin él, si no hace falta
  // elegir). Compartido entre el camino directo (0/1 plan usable) y el confirmado
  // desde el selector bulk (2+ planes usables).
  const runBulkReserve = async (reservables, studentPlanId) => {
    setWorkingKey('reserve-bulk')
    setError('')
    setNotice('')
    try {
      const results = await Promise.allSettled(
        reservables.map((item) => {
          const payload = { gym_class: item.id, status: 'active' }
          if (requiresPlanChoice) {
            payload.student_plan_id = Number(studentPlanId)
          }
          return enrollmentsApi.create(payload)
        }),
      )
      const successCount = results.filter((item) => item.status === 'fulfilled').length
      const failedCount = results.length - successCount
      await loadData()
      setSelectedAvailableIds([])
      if (failedCount > 0) {
        setError(`Se reservaron ${successCount} clases y ${failedCount} fallaron.`)
      } else {
        setNotice(`Se reservaron ${successCount} clases correctamente.`)
      }
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron reservar las clases seleccionadas.'))
    } finally {
      setWorkingKey('')
    }
  }

  const reserveSelectedAvailable = async () => {
    if (!hasPlanBalance) {
      setError('Sin clases disponibles')
      return
    }
    const selectedRows = filteredAvailableForBooking.filter((item) => selectedAvailableIds.includes(item.id))
    const now = Date.now()
    const reservables = selectedRows.filter((item) => {
      const started = new Date(item.start_datetime).getTime() <= now
      const recurringForTemplate = item.class_template ? recurringByTemplate[item.class_template] : null
      const pausedSeries = Boolean(item.class_template && recurringForTemplate && !recurringForTemplate.is_active)
      return item.status === 'scheduled' && !started && !pausedSeries
    })

    if (reservables.length === 0) {
      setError('No hay clases seleccionadas para reservar.')
      return
    }

    // Con 2+ planes usables, el selector se abre UNA vez para todo el lote; el
    // batch recién corre al confirmar (confirmPendingBulkReserve).
    if (requiresPlanChoice) {
      resetPlanSelection()
      setPendingBulkReserve(reservables)
      return
    }

    await runBulkReserve(reservables)
  }

  const confirmPendingBulkReserve = async () => {
    if (!pendingBulkReserve) {
      return
    }
    const reservables = pendingBulkReserve
    const planId = selectedPlanId
    await runBulkReserve(reservables, planId)
    setPendingBulkReserve(null)
    resetPlanSelection()
  }

  const availableColumns = useMemo(
    () => [
      { key: 'name', label: 'Clase', mobile: 'title' },
      { key: 'branch_name', label: 'Sucursal', mobile: 'secondary', mobilePriority: 4 },
      { key: 'teacher_name', label: 'Profesor', mobile: 'secondary', mobilePriority: 3 },
      { key: 'discipline_name', label: 'Disciplina', mobile: 'meta', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      { key: 'class_template_name', label: 'Serie', mobile: 'hidden', render: (row) => row.class_template_name || '-' },
      { key: 'start_datetime', label: 'Inicio', mobile: 'secondary', mobilePriority: 1, render: (row) => formatDateTime(row.start_datetime) },
      { key: 'end_datetime', label: 'Termino', mobile: 'hidden', render: (row) => formatDateTime(row.end_datetime) },
      { key: 'status', label: 'Estado', mobile: 'meta', render: (row) => <ValueBadge kind="class_status" value={row.status} /> },
      { key: 'capacity', label: 'Cupos', mobile: 'secondary', mobilePriority: 2, render: (row) => `${row.enrollments_count || 0}/${row.capacity}` },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        // Compact contextual button shown directly on the mobile card; full options stay in "Ver detalle".
        mobilePrimary: (row) => {
          const activeReservation = activeReservationByClass[row.id]
          if (activeReservation) {
            return (
              <button
                type="button"
                disabled={!activeReservation.can_cancel || workingKey === `cancel-${activeReservation.id}`}
                onClick={() => cancelReservation(activeReservation)}
                className="rounded-lg border border-brand-red/40 px-3 py-2 text-xs font-semibold text-red-200 disabled:opacity-60"
              >
                {workingKey === `cancel-${activeReservation.id}` ? 'Cancelando...' : 'Cancelar reserva'}
              </button>
            )
          }
          const recurringForTemplate = row.class_template ? recurringByTemplate[row.class_template] : null
          const classStarted = new Date(row.start_datetime).getTime() <= Date.now()
          const isPausedSeries = Boolean(row.class_template && recurringForTemplate && !recurringForTemplate.is_active)
          const canReserve = row.status === 'scheduled' && !classStarted && !isPausedSeries && hasPlanBalance
          return (
            <button
              type="button"
              disabled={!canReserve || workingKey === `reserve-${row.id}`}
              onClick={() => openSingleReserveConfirm(row)}
              title={!hasPlanBalance ? 'Sin clases disponibles' : ''}
              className="rounded-lg border border-brand-blue bg-brand-blue/10 px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-60"
            >
              {workingKey === `reserve-${row.id}` ? 'Reservando...' : 'Reservar'}
            </button>
          )
        },
        render: (row) => {
          const activeReservation = activeReservationByClass[row.id]
          const existingReservation = reservationByClass[row.id]
          const recurringForTemplate = row.class_template ? recurringByTemplate[row.class_template] : null
          const classStarted = new Date(row.start_datetime).getTime() <= Date.now()
          const isPausedSeries = Boolean(row.class_template && recurringForTemplate && !recurringForTemplate.is_active)
          const canReserveSingle = row.status === 'scheduled' && !classStarted && !isPausedSeries
          const canReserveWithPlan = canReserveSingle && hasPlanBalance
          const canManageRecurringHere = Boolean(row.class_template && row.status === 'scheduled' && !classStarted)
          const isRebook = existingReservation?.status === 'cancelled'

          return (
            <div className="space-y-2">
              {activeReservation ? (
                <div className="space-y-1">
                  {activeReservation.recurring_enrollment ? <ValueBadge kind="reservation_kind" value="recurring" /> : <ValueBadge kind="reservation_kind" value="single" />}
                  <button
                    type="button"
                    disabled={!activeReservation.can_cancel || workingKey === `cancel-${activeReservation.id}`}
                    onClick={() => cancelReservation(activeReservation)}
                    className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 disabled:opacity-60"
                  >
                    {workingKey === `cancel-${activeReservation.id}` ? 'Cancelando...' : 'Cancelar solo esta reserva'}
                  </button>
                  {!activeReservation.can_cancel && activeReservation.cancel_block_reason ? (
                    <p className="text-[11px] text-brand-muted">{activeReservation.cancel_block_reason}</p>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-1">
                  <button
                    type="button"
                    disabled={!canReserveWithPlan || workingKey === `reserve-${row.id}`}
                    onClick={() => openSingleReserveConfirm(row)}
                    className="w-full rounded-lg border border-brand-blue px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
                    title={!hasPlanBalance ? 'Sin clases disponibles' : ''}
                  >
                    {workingKey === `reserve-${row.id}` ? 'Reservando...' : isRebook ? 'Reservar esta clase' : 'Reservar solo esta clase'}
                  </button>
                  <div className="flex justify-end">
                    <TouchTooltip text={!hasPlanBalance ? 'Sin clases disponibles' : isRebook ? 'Reactivara tu reserva cancelada si sigue disponible.' : 'Reserva esta clase solo para esta fecha y horario.'} />
                  </div>
                  {isPausedSeries ? <p className="text-[11px] text-brand-muted">Serie pausada: reactiva o elimina para volver a reservar/cancelar.</p> : null}
                </div>
              )}

              {row.class_template ? (
                <div className="space-y-1 border-t border-brand-line pt-2">
                  {recurringForTemplate?.is_active ? <ValueBadge kind="reservation_kind" value="recurring" /> : null}
                  <button
                    type="button"
                    disabled={
                      !canManageRecurringHere ||
                      (recurringForTemplate && !recurringForTemplate.can_manage_now) ||
                      workingKey === `toggle-recurring-${recurringForTemplate?.id}` ||
                      workingKey === `recurring-${row.id}`
                    }
                    onClick={() => {
                      if (recurringForTemplate?.is_active) {
                        toggleRecurring(recurringForTemplate, false)
                        return
                      }
                      subscribeOrReactivateRecurring(row)
                    }}
                    className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
                  >
                    {recurringForTemplate?.is_active
                      ? workingKey === `toggle-recurring-${recurringForTemplate.id}`
                        ? 'Pausando...'
                        : 'Pausar recurrencia semanal'
                      : workingKey === `recurring-${row.id}`
                        ? 'Guardando...'
                        : recurringForTemplate
                          ? 'Reactivar recurrencia semanal'
                          : 'Inscribirme a esta serie semanal'}
                  </button>
                  <div className="flex justify-end gap-1">
                    {!recurringForTemplate ? <TouchTooltip text="Activa reservas automaticas para futuras clases de esta serie." /> : null}
                    {!canManageRecurringHere ? <TouchTooltip text="Solo se puede gestionar desde una clase programada y futura." /> : null}
                  </div>
                  {recurringForTemplate && !recurringForTemplate.can_manage_now && recurringForTemplate.manage_block_reason ? (
                    <p className="text-[11px] text-brand-muted">{recurringForTemplate.manage_block_reason}</p>
                  ) : null}
                </div>
              ) : (
                <div className="flex justify-end">
                  <TouchTooltip text="Clase unica: no aplica inscripcion recurrente." />
                </div>
              )}
            </div>
          )
        },
      },
    ],
    [activeReservationByClass, hasPlanBalance, recurringByTemplate, reservationByClass, workingKey],
  )

  const reservationColumns = useMemo(
    () => [
      { key: 'gym_class_name', label: 'Clase', mobile: 'title' },
      { key: 'class_branch_name', label: 'Sucursal', mobile: 'secondary', mobilePriority: 3 },
      { key: 'class_teacher_name', label: 'Profesor', mobile: 'secondary', mobilePriority: 2 },
      { key: 'class_discipline_name', label: 'Disciplina', mobile: 'hidden', render: (row) => <ValueBadge kind="discipline" value={row.class_discipline_name} /> },
      { key: 'class_type_name', label: 'Tipo clase', mobile: 'hidden', render: (row) => <ValueBadge kind="class_type" value={row.class_type_name} /> },
      { key: 'class_start', label: 'Inicio', mobile: 'secondary', mobilePriority: 1, render: (row) => formatDateTime(row.class_start) },
      { key: 'class_end', label: 'Termino', mobile: 'hidden', render: (row) => formatDateTime(row.class_end) },
      {
        key: 'reservation_kind',
        label: 'Modalidad',
        mobile: 'meta',
        render: (row) => <ValueBadge kind="reservation_kind" value={row.reservation_kind} />,
      },
      {
        key: 'status',
        label: 'Reserva',
        mobile: 'meta',
        render: (row) => <ValueBadge kind="enrollment_status" value={row.status} />,
      },
      {
        key: 'attendance_status',
        label: 'Asistencia',
        mobile: 'meta',
        render: (row) =>
          row.attendance_status ? <ValueBadge kind="attendance_status" value={row.attendance_status} /> : <span className="text-brand-muted">-</span>,
      },
      { key: 'class_status', label: 'Estado clase', mobile: 'hidden', render: (row) => <ValueBadge kind="class_status" value={row.class_status} /> },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        mobilePrimary: (row) =>
          row.status === 'active' && row.can_cancel ? (
            <button
              type="button"
              disabled={workingKey === `cancel-${row.id}`}
              onClick={() => cancelReservation(row)}
              className="rounded-lg border border-brand-red/40 px-3 py-2 text-xs font-semibold text-red-200 disabled:opacity-60"
            >
              {workingKey === `cancel-${row.id}` ? 'Cancelando...' : 'Cancelar reserva'}
            </button>
          ) : null,
        render: (row) => {
          const recurringItem = row.recurring_enrollment ? recurringById[row.recurring_enrollment] : null
          const recurringForTemplate = row.class_template_id ? recurringByTemplate[row.class_template_id] : null
          const isPausedSeries = Boolean(recurringForTemplate && !recurringForTemplate.is_active)
          const classStarted = new Date(row.class_start).getTime() <= Date.now()
          const canRebook = row.status === 'cancelled' && row.class_status === 'scheduled' && !classStarted && !isPausedSeries
          return (
            <div className="space-y-2">
              <button
                type="button"
                disabled={row.status !== 'active' || !row.can_cancel || workingKey === `cancel-${row.id}` || workingKey === `reserve-reservation-${row.id}`}
                onClick={() => cancelReservation(row)}
                className="w-full rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-left text-xs text-red-200 disabled:opacity-60"
              >
                {workingKey === `cancel-${row.id}` ? 'Cancelando...' : 'Cancelar solo esta reserva'}
              </button>
              {row.status === 'active' && !row.can_cancel && row.cancel_block_reason ? <p className="text-[11px] text-brand-muted">{row.cancel_block_reason}</p> : null}
              {canRebook ? (
                <button
                  type="button"
                  disabled={isPausedSeries || workingKey === `reserve-reservation-${row.id}` || workingKey === `cancel-${row.id}`}
                  onClick={() => handleReserveFromReservationClick(row)}
                  className="w-full rounded-lg border border-brand-blue px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
                >
                  {workingKey === `reserve-reservation-${row.id}` ? 'Reservando...' : 'Reservar'}
                </button>
              ) : null}
              {isPausedSeries ? <p className="text-[11px] text-brand-muted">Serie pausada: reactiva o elimina para volver a gestionar reservas.</p> : null}
              {row.status === 'cancelled' && !canRebook ? (
                <div className="flex justify-end">
                  <TouchTooltip text="Esta reserva ya no puede reactivarse desde esta vista." />
                </div>
              ) : null}
              {recurringItem ? (
                <>
                  <button
                    type="button"
                    disabled={!recurringItem.can_manage_now || workingKey === `toggle-recurring-${recurringItem.id}`}
                    onClick={() => toggleRecurring(recurringItem, !recurringItem.is_active)}
                    className="w-full rounded-lg border border-brand-orange/50 px-2.5 py-1.5 text-left text-xs text-brand-white disabled:opacity-60"
                  >
                    {workingKey === `toggle-recurring-${recurringItem.id}`
                      ? 'Actualizando...'
                      : recurringItem.is_active
                        ? 'Pausar recurrencia semanal'
                        : 'Reactivar recurrencia semanal'}
                  </button>
                  {!recurringItem.can_manage_now && recurringItem.manage_block_reason ? (
                    <p className="text-[11px] text-brand-muted">{recurringItem.manage_block_reason}</p>
                  ) : null}
                </>
              ) : null}
            </div>
          )
        },
      },
    ],
    [recurringById, recurringByTemplate, requiresPlanChoice, workingKey],
  )

  const historyColumns = useMemo(
    () => [
      { key: 'name', label: 'Clase', mobile: 'title' },
      { key: 'branch_name', label: 'Sucursal', mobile: 'secondary', mobilePriority: 3 },
      { key: 'teacher_name', label: 'Profesor', mobile: 'secondary', mobilePriority: 2 },
      { key: 'discipline_name', label: 'Disciplina', mobile: 'hidden', render: (row) => <ValueBadge kind="discipline" value={row.discipline_name} /> },
      { key: 'start_datetime', label: 'Inicio', mobile: 'secondary', mobilePriority: 1, render: (row) => formatDateTime(row.start_datetime) },
      { key: 'end_datetime', label: 'Termino', mobile: 'hidden', render: (row) => formatDateTime(row.end_datetime) },
      { key: 'status', label: 'Estado final', mobile: 'meta', render: (row) => <ValueBadge kind="class_status" value={row.status} /> },
    ],
    [],
  )

  // El baseline de "activos"/"Limpiar" es SIEMPRE el set vacío (initialClassFilters):
  // así el rango por defecto (semana) cuenta como filtro activo → el botón "Limpiar"
  // aparece y, al pulsarlo, quita TODOS los filtros incluido el rango (no vuelve a la
  // semana). El default de montaje (semana) se fija sólo en el useState, no aquí.
  const renderClassFilters = (filters, setFilters, options) => (
    <FilterPanel activeCount={countActiveFilters(filters, initialClassFilters)} onClear={() => setFilters(initialClassFilters)}>
      <div className="space-y-3">
        <QuickChips
          items={[
            { label: 'Hoy', active: filters.dateRange === 'today', onClick: () => setFilters((prev) => ({ ...prev, dateRange: prev.dateRange === 'today' ? '' : 'today' })) },
            { label: 'Semana', active: filters.dateRange === 'week', onClick: () => setFilters((prev) => ({ ...prev, dateRange: prev.dateRange === 'week' ? '' : 'week' })) },
          ]}
        />
        <div className="flex flex-wrap items-end gap-2">
          <FilterDropdown label="Profesor" value={filters.teacher} options={options.teacherOptions} onChange={(value) => setFilters((prev) => ({ ...prev, teacher: value }))} />
          <FilterDropdown label="Disciplina" value={filters.discipline} options={options.disciplineOptions} onChange={(value) => setFilters((prev) => ({ ...prev, discipline: value }))} />
          <FilterDropdown label="Estado" value={filters.status} options={CLASS_STATUS_OPTIONS} onChange={(value) => setFilters((prev) => ({ ...prev, status: value }))} />
        </div>
      </div>
    </FilterPanel>
  )

  const renderReservationFilters = () => (
    <FilterPanel activeCount={countActiveFilters(reservationFilters, initialReservationFilters)} onClear={() => setReservationFilters(initialReservationFilters)}>
      <div className="space-y-3">
        <QuickChips
          items={[
            { label: 'Hoy', active: reservationFilters.dateRange === 'today', onClick: () => setReservationFilters((prev) => ({ ...prev, dateRange: prev.dateRange === 'today' ? '' : 'today' })) },
            { label: 'Semana', active: reservationFilters.dateRange === 'week', onClick: () => setReservationFilters((prev) => ({ ...prev, dateRange: prev.dateRange === 'week' ? '' : 'week' })) },
          ]}
        />
        <div className="flex flex-wrap items-end gap-2">
          <FilterDropdown
            label="Profesor"
            value={reservationFilters.teacher}
            options={reservationFilterOptions.teacherOptions}
            onChange={(value) => setReservationFilters((prev) => ({ ...prev, teacher: value }))}
          />
          <FilterDropdown
            label="Disciplina"
            value={reservationFilters.discipline}
            options={reservationFilterOptions.disciplineOptions}
            onChange={(value) => setReservationFilters((prev) => ({ ...prev, discipline: value }))}
          />
          <FilterDropdown
            label="Estado"
            value={reservationFilters.status}
            options={RESERVATION_STATUS_OPTIONS}
            onChange={(value) => setReservationFilters((prev) => ({ ...prev, status: value }))}
          />
          <FilterDropdown
            label="Tipo clase"
            value={reservationFilters.classType}
            options={reservationFilterOptions.classTypeOptions}
            onChange={(value) => setReservationFilters((prev) => ({ ...prev, classType: value }))}
          />
          <FilterDropdown
            label="Modalidad"
            value={reservationFilters.mode}
            options={RESERVATION_MODE_OPTIONS}
            onChange={(value) => setReservationFilters((prev) => ({ ...prev, mode: value }))}
          />
        </div>
      </div>
    </FilterPanel>
  )

  const viewConfig = useMemo(
    () => ({
      available: {
        title: 'Clases disponibles',
        subtitle: 'Reserva puntual o suscríbete a una serie semanal según corresponda.',
        columns: availableColumns,
        data: filteredAvailableForBooking,
        defaultSort: { key: 'start_datetime', direction: 'asc' },
      },
      reservations: {
        title: 'Mis reservas',
        subtitle: 'Gestiona reservas individuales y recurrentes sin confundir sus acciones.',
        columns: reservationColumns,
        data: filteredReservations,
        defaultSort: { key: 'class_start', direction: 'asc' },
      },
      history: {
        title: 'Historial de clases',
        subtitle: 'Registro de clases finalizadas en tu agenda.',
        columns: historyColumns,
        data: filteredHistory,
        defaultSort: { key: 'start_datetime', direction: 'desc' },
      },
    }),
    [availableColumns, filteredAvailableForBooking, filteredHistory, filteredReservations, historyColumns, reservationColumns],
  )

  const activeView = viewConfig[mode] || viewConfig.available
  const policyMessage = reservations.find((item) => item.cancel_policy_message)?.cancel_policy_message || recurringItems.find((item) => item.manage_policy_message)?.manage_policy_message
  const selectedAvailable = filteredAvailableForBooking.filter((item) => selectedAvailableIds.includes(item.id))
  const selectedReservations = filteredReservations.filter((item) => selectedReservationIds.includes(item.id))
  const cancellableSelectedCount = selectedReservations.filter((item) => item.status === 'active' && item.can_cancel).length

  // Los tres flujos de reserva (individual, rebook, bulk) comparten un único
  // ConfirmDialog: a lo sumo uno de los tres estados pendientes está activo a la vez.
  const pendingReserveKind = pendingReserve ? 'single' : pendingRebook ? 'rebook' : pendingBulkReserve ? 'bulk' : null
  const showPlanSelector = pendingReserveKind !== null && requiresPlanChoice
  const confirmDialogOpen = pendingReserveKind !== null
  const confirmDialogLoading =
    pendingReserveKind === 'single'
      ? workingKey === `reserve-${pendingReserve?.id}`
      : pendingReserveKind === 'rebook'
        ? workingKey === `reserve-reservation-${pendingRebook?.id}`
        : pendingReserveKind === 'bulk'
          ? workingKey === 'reserve-bulk'
          : false
  const confirmDialogTitle = pendingReserveKind === 'bulk' ? 'Elige tu plan' : 'Confirmar reserva'
  const confirmDialogDescription =
    pendingReserveKind === 'bulk'
      ? `Vas a reservar ${pendingBulkReserve?.length || 0} clases. Elige con qué plan.`
      : '¿Seguro que quieres reservar esta clase? Se descontará una clase de tu plan.'
  const confirmDialogLabel = pendingReserveKind === 'bulk' ? 'Reservar seleccionadas' : 'Reservar'
  const confirmDialogDisabled = showPlanSelector && !selectedPlanId
  const handleConfirmDialogConfirm = () => {
    if (pendingReserveKind === 'single') {
      return confirmPendingReserve()
    }
    if (pendingReserveKind === 'rebook') {
      return confirmPendingRebook()
    }
    if (pendingReserveKind === 'bulk') {
      return confirmPendingBulkReserve()
    }
    return undefined
  }
  const handleConfirmDialogCancel = () => {
    setPendingReserve(null)
    setPendingRebook(null)
    setPendingBulkReserve(null)
    resetPlanSelection()
  }

  return (
    <div className="space-y-6">
      <DashboardHeader title="Student · Mis clases" subtitle="Agenda clara para reserva individual y recurrencia semanal." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}
      {policyMessage ? <p className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs text-brand-muted">{policyMessage}</p> : null}

      <section className="card-surface space-y-4 p-5">
        {mode === 'available' ? (
          <>
            <div className="flex items-center gap-2 rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs">
              <span className="text-brand-muted">Te quedan</span>
              <span className={`inline-flex rounded-full border px-2 py-0.5 font-semibold ${hasPlanBalance ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
                {balanceChipLabel}
              </span>
            </div>
            <KpiStrip
              items={[
                { label: 'Total clases visibles', value: availableKpis.totalVisible },
                { label: 'Mis reservas activas (visibles)', value: availableKpis.activeVisible },
                { label: 'Próximas clases mías', value: availableKpis.upcomingMine },
              ]}
            />
            {renderClassFilters(classFilters, setClassFilters, availableFilterOptions)}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs">
              <span className="text-brand-muted">Seleccionadas: {selectedAvailable.length}</span>
              <button
                type="button"
                disabled={selectedAvailable.length === 0 || workingKey === 'reserve-bulk' || !hasPlanBalance}
                onClick={reserveSelectedAvailable}
                className="rounded-lg border border-brand-blue px-2.5 py-1.5 text-brand-white disabled:opacity-60"
                title={!hasPlanBalance ? 'Sin clases disponibles' : ''}
              >
                {workingKey === 'reserve-bulk' ? 'Reservando seleccion...' : 'Reservar seleccionadas'}
              </button>
            </div>
          </>
        ) : null}

        {mode === 'reservations' ? (
          <>
            <KpiStrip
              items={[
                { label: 'Total reservas', value: reservationKpis.total },
                { label: 'Próximas reservas', value: reservationKpis.upcoming },
                { label: 'Recurrencias activas', value: reservationKpis.recurringActive },
              ]}
            />
            {renderReservationFilters()}
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs">
              <span className="text-brand-muted">Seleccionadas: {selectedReservations.length}</span>
              <span className="text-brand-muted">Cancelables: {cancellableSelectedCount}</span>
              <button
                type="button"
                disabled={cancellableSelectedCount === 0 || workingKey === 'cancel-bulk'}
                onClick={cancelSelectedReservations}
                className="rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-red-200 disabled:opacity-60"
              >
                {workingKey === 'cancel-bulk' ? 'Cancelando seleccion...' : 'Cancelar seleccionadas'}
              </button>
            </div>
          </>
        ) : null}

        {mode === 'history' ? renderClassFilters(historyFilters, setHistoryFilters, historyFilterOptions) : null}
      </section>

      <section className="card-surface p-5">
        <h2 className="panel-title mb-1">{activeView.title}</h2>
        <p className="mb-4 text-xs text-brand-muted">{activeView.subtitle}</p>
        <DataTable
          columns={activeView.columns}
          data={activeView.data}
          loading={loading}
          defaultSort={activeView.defaultSort}
          selectableRows={mode === 'reservations' || mode === 'available'}
          selectedRowIds={mode === 'reservations' ? selectedReservationIds : mode === 'available' ? selectedAvailableIds : []}
          onSelectedRowIdsChange={mode === 'reservations' ? setSelectedReservationIds : mode === 'available' ? setSelectedAvailableIds : undefined}
          selectAllScope="filtered"
        />
      </section>

      <ConfirmDialog
        open={confirmDialogOpen}
        title={confirmDialogTitle}
        description={confirmDialogDescription}
        confirmLabel={confirmDialogLabel}
        loading={confirmDialogLoading}
        confirmDisabled={confirmDialogDisabled}
        onConfirm={handleConfirmDialogConfirm}
        onCancel={handleConfirmDialogCancel}
      >
        {showPlanSelector ? (
          <div className="mt-3 space-y-1 text-left">
            <label className="text-xs text-brand-muted" htmlFor="reserve-plan-select">
              Elige con qué plan reservar
            </label>
            <select
              id="reserve-plan-select"
              value={selectedPlanId}
              onChange={(event) => setSelectedPlanId(event.target.value)}
              className="w-full rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm text-brand-white"
            >
              <option value="">Selecciona un plan</option>
              {usableMemberships.map((membership) => (
                <option key={membership.id} value={membership.id}>
                  {membership.remaining_classes === null
                    ? `${membership.plan_name} — clases ilimitadas`
                    : `${membership.plan_name} — quedan ${membership.remaining_classes}`}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </ConfirmDialog>
    </div>
  )
}
