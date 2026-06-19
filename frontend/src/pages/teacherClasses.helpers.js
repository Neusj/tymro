export const UPCOMING_STATUS_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'scheduled', label: 'Programada' },
  { value: 'in_progress', label: 'En curso' },
  { value: 'suspended', label: 'Suspendida' },
]

export const HISTORY_STATUS_OPTIONS = [
  { value: '', label: 'Todas' },
  { value: 'completed', label: 'Finalizada' },
  { value: 'completed_early', label: 'Finalizada anticipadamente' },
]

export function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function formatClassStatus(status) {
  const statusMap = {
    scheduled: 'Programada',
    in_progress: 'En curso',
    completed: 'Finalizada',
    cancelled: 'Cancelada',
    completed_early: 'Finalizada anticipadamente',
    suspended: 'Suspendida',
  }
  return statusMap[status] || status || '-'
}

export function extractFilterOptions(classes) {
  const disciplines = new Set()

  classes.forEach((item) => {
    if (item.discipline_name) {
      disciplines.add(item.discipline_name)
    }
  })

  return {
    disciplineOptions: [
      { value: '', label: 'Todas' },
      ...Array.from(disciplines).sort((a, b) => a.localeCompare(b, 'es')).map((value) => ({ value, label: value })),
    ],
  }
}

export function applyTeacherClassFilters(classes, filters) {
  return classes.filter((item) => {
    if (filters.status && item.status !== filters.status) {
      return false
    }
    if (filters.discipline && item.discipline_name !== filters.discipline) {
      return false
    }
    return true
  })
}

export function calculateTeacherKpis(classes, mode) {
  const totalClasses = classes.length
  const totalCapacity = classes.reduce((sum, item) => sum + (Number(item.capacity) || 0), 0)

  if (mode === 'history') {
    const totalAttendees = classes.reduce(
      (sum, item) => sum + (Number(item.present_attendances_count ?? item.attendances_count ?? 0) || 0),
      0,
    )
    const occupancy = totalCapacity > 0 ? Number(((totalAttendees / totalCapacity) * 100).toFixed(2)) : 0
    return {
      totalClasses,
      totalPeople: totalAttendees,
      occupancy,
      peopleLabel: 'Total asistentes',
    }
  }

  const totalEnrolled = classes.reduce((sum, item) => sum + (Number(item.enrollments_count) || 0), 0)
  const occupancy = totalCapacity > 0 ? Number(((totalEnrolled / totalCapacity) * 100).toFixed(2)) : 0
  return {
    totalClasses,
    totalPeople: totalEnrolled,
    occupancy,
    peopleLabel: 'Total inscritos',
  }
}

export function canOperateClass(gymClass) {
  return !['completed', 'cancelled', 'completed_early'].includes(gymClass.status)
}
