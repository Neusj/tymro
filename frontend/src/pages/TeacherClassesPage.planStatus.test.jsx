import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  classesApi: {
    list: vi.fn(),
    enrollableStudents: vi.fn(),
    enrolledStudents: vi.fn(),
  },
  enrollmentsApi: { create: vi.fn(), cancel: vi.fn() },
}))

import { classesApi } from '../api/client'
import TeacherClassesPage from './TeacherClassesPage'

const DAY = 24 * 60 * 60 * 1000

const GYM_CLASS = {
  id: 101,
  name: 'BJJ Fundamentos',
  branch_name: 'Sede',
  class_type_name: 'Regular',
  discipline_name: 'BJJ',
  status: 'scheduled',
  capacity: 10,
  enrollments_count: 0,
  start_datetime: new Date(Date.now() + DAY).toISOString(),
  end_datetime: new Date(Date.now() + DAY + 3600000).toISOString(),
}

// Fila tal como la manda el roster (`enrollable-students`) despues de 7.3.
function candidate(overrides = {}) {
  return {
    id: 5,
    username: 'ana',
    name: 'Ana Perez',
    email: 'ana@test.local',
    available_classes: 8,
    has_available_classes: true,
    unlimited_classes: false,
    plan_status: 'active',
    plan_status_label: 'Vigente',
    plan_days_to_expiry: 20,
    plan_reason_code: null,
    plan_expiry_alert_level: 'safe',
    plan_expiry_alert_message: '20 dias vigentes',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.list.mockResolvedValue([GYM_CLASS])
  classesApi.enrolledStudents.mockResolvedValue([])
  classesApi.enrollableStudents.mockResolvedValue([candidate()])
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'),
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
})

afterEach(() => {
  delete window.matchMedia
})

// DataTable pinta la tabla de escritorio Y las tarjetas móviles a la vez (las alterna por
// CSS), asi que cada celda y cada acción aparecen dos veces en el DOM.
const shown = (text) => screen.queryAllByText(text).length

async function openEnrollModal() {
  render(<TeacherClassesPage mode="upcoming" />)
  await waitFor(() => expect(shown('BJJ Fundamentos')).toBeGreaterThan(0))
  // Las acciones de fila viven detrás del engranaje de DataTable (RowActionsDropdown).
  await userEvent.click(screen.getAllByRole('button', { name: 'Abrir acciones' })[0])
  await userEvent.click(await screen.findByRole('button', { name: 'Inscribir alumnos' }))
  await waitFor(() => expect(shown('Ana Perez')).toBeGreaterThan(0))
  return screen.getAllByText('Ana Perez')[0].closest('label')
}

describe('TeacherClassesPage — badge de plan en el roster', () => {
  it('pinta el aviso del backend en vez de reescribirlo', async () => {
    const row = await openEnrollModal()

    expect(within(row).getByText('20 dias vigentes')).toBeInTheDocument()
  })

  it('no dice "Sin plan" a un alumno cuyo plan se quedó sin clases', async () => {
    // El `else` de :76 mandaba a "Sin plan" cualquier estado que no reconociera, y
    // exhausted/enrollment_fee_unpaid eran exactamente eso.
    classesApi.enrollableStudents.mockResolvedValue([
      candidate({
        available_classes: 0,
        has_available_classes: false,
        plan_status: 'exhausted',
        plan_status_label: 'Sin clases disponibles',
        plan_reason_code: 'plan_unavailable',
        plan_expiry_alert_level: 'danger',
        plan_expiry_alert_message: 'Sin clases disponibles',
      }),
    ])

    const row = await openEnrollModal()

    expect(within(row).getByText('Sin clases disponibles')).toBeInTheDocument()
    expect(shown('Sin plan')).toBe(0)
  })

  it('no ofrece inscribir a quien debe la matrícula, aunque tenga saldo', async () => {
    classesApi.enrollableStudents.mockResolvedValue([
      candidate({
        available_classes: 8,
        has_available_classes: false,
        plan_status: 'enrollment_fee_unpaid',
        plan_status_label: 'Matrícula impaga',
        plan_reason_code: 'enrollment_fee_unpaid',
        plan_expiry_alert_level: 'danger',
        plan_expiry_alert_message: 'Matrícula impaga',
      }),
    ])

    const row = await openEnrollModal()

    expect(within(row).getByRole('checkbox')).toBeDisabled()
    // El saldo se sigue diciendo tal cual: las 8 clases existen, lo que falta es la matrícula.
    expect(within(row).getByText('8 clases')).toBeInTheDocument()
    expect(within(row).getByText('Matrícula impaga')).toBeInTheDocument()
  })
})
