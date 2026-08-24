export const CLASS_STATUS_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'scheduled', label: 'Programada' },
  { value: 'in_progress', label: 'En curso' },
  { value: 'cancelled', label: 'Cancelada' },
  { value: 'completed', label: 'Finalizada' },
  { value: 'completed_early', label: 'Finalizada anticipadamente' },
]

export const RESERVATION_STATUS_OPTIONS = [
  { value: 'active', label: 'Activas' },
  { value: 'finished', label: 'Finalizadas' },
  { value: 'cancelled', label: 'Canceladas' },
]

export const RESERVATION_MODE_OPTIONS = [
  { value: '', label: 'Todas' },
  { value: 'single', label: 'Individual' },
  { value: 'recurring', label: 'Recurrente' },
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

export function formatTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleTimeString('es-CL', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatTimeRange(start, end) {
  if (!start) {
    return '-'
  }
  return end ? `${formatTime(start)} - ${formatTime(end)}` : formatTime(start)
}

function toOptions(values, defaultLabel = 'Todos') {
  return [{ value: '', label: defaultLabel }, ...Array.from(values).sort((a, b) => a.localeCompare(b, 'es')).map((value) => ({ value, label: value }))]
}

export function extractStudentClassOptions(classes) {
  const teachers = new Set()
  const disciplines = new Set()

  classes.forEach((item) => {
    if (item.teacher_name) {
      teachers.add(item.teacher_name)
    }
    if (item.discipline_name) {
      disciplines.add(item.discipline_name)
    }
  })

  return {
    teacherOptions: toOptions(teachers),
    disciplineOptions: toOptions(disciplines),
  }
}

export function extractStudentReservationOptions(reservations) {
  const teachers = new Set()
  const disciplines = new Set()
  const classTypes = new Set()

  reservations.forEach((item) => {
    if (item.class_teacher_name) {
      teachers.add(item.class_teacher_name)
    }
    if (item.class_discipline_name) {
      disciplines.add(item.class_discipline_name)
    }
    if (item.class_type_name) {
      classTypes.add(item.class_type_name)
    }
  })

  return {
    teacherOptions: toOptions(teachers),
    disciplineOptions: toOptions(disciplines),
    classTypeOptions: toOptions(classTypes),
  }
}

export function extractStudentRecurringOptions(items) {
  const teachers = new Set()
  const disciplines = new Set()

  items.forEach((item) => {
    if (item.template_teacher_name) {
      teachers.add(item.template_teacher_name)
    }
    if (item.template_discipline_name) {
      disciplines.add(item.template_discipline_name)
    }
  })

  return {
    teacherOptions: toOptions(teachers),
    disciplineOptions: toOptions(disciplines),
  }
}

export function applyStudentClassFilters(classes, filters) {
  return classes.filter((item) => {
    if (filters.teacher && item.teacher_name !== filters.teacher) {
      return false
    }
    if (filters.discipline && item.discipline_name !== filters.discipline) {
      return false
    }
    if (filters.status && item.status !== filters.status) {
      return false
    }
    if (!matchesDateRange(item.start_datetime, filters.dateRange)) {
      return false
    }
    return true
  })
}

export function applyStudentReservationFilters(reservations, filters) {
  const selectedStatus = filters.status || 'active'
  return reservations.filter((item) => {
    if (filters.teacher && item.class_teacher_name !== filters.teacher) {
      return false
    }
    if (filters.discipline && item.class_discipline_name !== filters.discipline) {
      return false
    }
    if (selectedStatus && getReservationBucket(item) !== selectedStatus) {
      return false
    }
    if (filters.classType && item.class_type_name !== filters.classType) {
      return false
    }
    if (filters.mode && item.reservation_kind !== filters.mode) {
      return false
    }
    if (!matchesDateRange(item.class_start, filters.dateRange)) {
      return false
    }
    return true
  })
}

export function getReservationBucket(item) {
  if (item.status === 'cancelled') {
    return 'cancelled'
  }
  if (['completed', 'completed_early'].includes(item.class_status)) {
    return 'finished'
  }
  const classEnd = new Date(item.class_end || item.class_start).getTime()
  if (!Number.isNaN(classEnd) && classEnd < Date.now()) {
    return 'finished'
  }
  return 'active'
}

function matchesDateRange(value, dateRange) {
  if (!dateRange) {
    return true
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return false
  }
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startTomorrow = new Date(startToday)
  startTomorrow.setDate(startTomorrow.getDate() + 1)
  if (dateRange === 'today') {
    return date >= startToday && date < startTomorrow
  }
  if (dateRange === 'week') {
    const endWeek = new Date(startToday)
    endWeek.setDate(endWeek.getDate() + 7)
    return date >= startToday && date < endWeek
  }
  return true
}

export function applyStudentRecurringFilters(items, filters) {
  return items.filter((item) => {
    if (filters.teacher && item.template_teacher_name !== filters.teacher) {
      return false
    }
    if (filters.discipline && item.template_discipline_name !== filters.discipline) {
      return false
    }
    if (filters.status === 'active' && !item.is_active) {
      return false
    }
    if (filters.status === 'paused' && item.is_active) {
      return false
    }
    return true
  })
}

export function calculateAvailableKpis(filteredClasses, activeReservationByClass) {
  const now = Date.now()
  const totalVisible = filteredClasses.length
  const activeVisible = filteredClasses.filter((item) => Boolean(activeReservationByClass[item.id])).length
  const upcomingMine = filteredClasses.filter((item) => {
    const reservation = activeReservationByClass[item.id]
    if (!reservation) {
      return false
    }
    return new Date(item.start_datetime).getTime() > now
  }).length

  return {
    totalVisible,
    activeVisible,
    upcomingMine,
  }
}

export function calculateReservationKpis(filteredReservations) {
  const now = Date.now()
  const recurringActiveIds = new Set()
  let upcoming = 0
  let inProgress = 0

  filteredReservations.forEach((item) => {
    if (item.status === 'active' && new Date(item.class_start).getTime() > now) {
      upcoming += 1
    }
    if (item.status === 'active' && item.class_status === 'in_progress') {
      inProgress += 1
    }
    if (item.recurring_enrollment && item.recurring_is_active) {
      recurringActiveIds.add(item.recurring_enrollment)
    }
  })

  return {
    total: filteredReservations.length,
    upcoming,
    inProgress,
    recurringActive: recurringActiveIds.size,
  }
}

export function calculateRecurringKpis(filteredRecurring) {
  return {
    total: filteredRecurring.length,
    active: filteredRecurring.filter((item) => item.is_active).length,
    paused: filteredRecurring.filter((item) => !item.is_active).length,
  }
}
