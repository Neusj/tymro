import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  getStudentOverview: vi.fn(),
  studentOverviewDetailsApi: {
    reservations: vi.fn(),
    attendance: vi.fn(),
    consumption: vi.fn(),
    memberships: vi.fn(),
    recurringReservations: vi.fn(),
  },
  usersApi: { list: vi.fn() },
}))

import { getStudentOverview, studentOverviewDetailsApi, usersApi } from '../api/client'
import GymAdminStudentOverviewPage from './GymAdminStudentOverviewPage'

function membership(overrides = {}) {
  return {
    id: 1,
    plan_name: 'Pack 10',
    start_date: '2026-07-01',
    end_date: '2026-07-30',
    total_classes: 10,
    unlimited_classes: false,
    classes_used: 2,
    remaining_classes: 8,
    validity_status: 'active',
    validity_status_label: 'Vigente',
    expiry_alert_level: 'safe',
    expiry_alert_message: '20 dias vigentes',
    payment_status: 'paid',
    enrollment_fee_status: { status: 'waived' },
    ...overrides,
  }
}

function summary(overrides = {}) {
  return {
    period: { key: '30d', label: 'Ultimos 30 dias', start_date: '2026-07-12', end_date: '2026-08-10' },
    memberships: { active_count: 1, active_items: [membership()], historical_count: 2 },
    reservations: {
      future_active_total: 5,
      by_discipline: [{ discipline_id: 1, discipline_name: 'Kickboxing', total: 4 }],
      upcoming: [
        {
          id: 10,
          status: 'active',
          class: { id: 99, name: 'Kick 19h', start_datetime: '2026-08-10T19:00:00Z', discipline_name: 'Kickboxing' },
        },
      ],
    },
    consumption: { total: 18, by_discipline: [{ discipline_id: 1, discipline_name: 'Kickboxing', total: 8 }] },
    attendance: {
      present: 24,
      absences: 3,
      attendance_rate: 88.9,
      denominator: 27,
      formula: 'present / (present + absent + no_show)',
      by_status: {},
      by_discipline: [{ discipline_id: 1, discipline_name: 'Kickboxing', total: 24 }],
    },
    recurring_reservations: {
      active_total: 2,
      preview: [
        { id: 7, class_template: { name: 'Kick semanal', weekday: 0, start_time: '19:00:00', discipline_name: 'Kickboxing' } },
      ],
    },
    ...overrides,
  }
}

function overview(overrides = {}) {
  return {
    student: {
      id: 42,
      username: 'ana',
      name: 'Ana Perez',
      email: 'ana@test.local',
      phone: '999',
      role: 'student',
      is_active: true,
      branch_id: null,
      branch_name: 'Sede Centro',
    },
    summary: summary(),
    memberships: [membership(), membership({ id: 2, plan_name: 'Plan viejo', validity_status: 'expired' })],
    consumption: { items: [], limit: 20, has_more: false },
    attendance: { items: [], limit: 20, has_more: false },
    reservations: { items: [], limit: 20, has_more: false },
    recurring_enrollments: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  usersApi.list.mockResolvedValue([])
  Object.values(studentOverviewDetailsApi).forEach((fn) => {
    fn.mockResolvedValue({ items: [], count: 0, page: 1, page_size: 20, has_next: false, has_previous: false })
  })
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'),
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
})

function renderPage(initialEntry = '/gym-admin/students/overview?student_id=42') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <GymAdminStudentOverviewPage />
    </MemoryRouter>,
  )
}

describe('GymAdminStudentOverviewPage', () => {
  it('carga el summary inicial y renderiza un dashboard compacto', async () => {
    getStudentOverview.mockResolvedValue(overview())

    renderPage()

    await waitFor(() => expect(screen.getByText('Ana Perez')).toBeInTheDocument())
    expect(screen.getByText('Pack 10')).toBeInTheDocument()
    expect(screen.getByText('Pagado')).toBeInTheDocument()
    expect(screen.getAllByText('5').length).toBeGreaterThan(0)
    expect(screen.getAllByText('18').length).toBeGreaterThan(0)
    expect(screen.getAllByText('88.9%').length).toBeGreaterThan(0)
    expect(screen.queryByText('Plan viejo')).not.toBeInTheDocument()
    expect(screen.getByText('2 membresias anteriores')).toBeInTheDocument()
    expect(getStudentOverview).toHaveBeenCalledWith('42', { period: '30d' })
  })

  it('sin alumno seleccionado no llama al endpoint y muestra el estado inicial', async () => {
    renderPage('/gym-admin/students/overview')

    await waitFor(() => expect(screen.getByText('Sin alumno seleccionado')).toBeInTheDocument())
    expect(getStudentOverview).not.toHaveBeenCalled()
  })

  it('muestra el error del backend si la carga falla', async () => {
    getStudentOverview.mockRejectedValue({ response: { data: { detail: 'No encontrado.' } } })

    renderPage()

    await waitFor(() => expect(screen.getByText('No encontrado.')).toBeInTheDocument())
  })

  it('cambiar periodo recarga KPIs con parametros backend', async () => {
    getStudentOverview.mockResolvedValue(overview())

    renderPage()

    await waitFor(() => expect(screen.getByText('Ana Perez')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Periodo'), { target: { value: '90d' } })

    await waitFor(() => expect(getStudentOverview).toHaveBeenLastCalledWith('42', { period: '90d' }))
  })

  it('cambiar alumno limpia el detalle y carga el nuevo id', async () => {
    usersApi.list.mockResolvedValue([{ id: 55, first_name: 'Beto', last_name: '', username: 'beto', email: 'b@test.local' }])
    getStudentOverview.mockResolvedValue(overview())

    renderPage()

    await waitFor(() => expect(screen.getByText('Ana Perez')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Alumno'), { target: { value: '55' } })

    await waitFor(() => expect(getStudentOverview).toHaveBeenLastCalledWith('55', { period: '30d' }))
  })

  it('abre detalle de reservas bajo demanda sin recargar overview completo', async () => {
    getStudentOverview.mockResolvedValue(overview())
    studentOverviewDetailsApi.reservations.mockResolvedValue({
      items: [
        {
          id: 10,
          status: 'active',
          class: { id: 99, name: 'Kick 19h', start_datetime: '2026-08-10T19:00:00Z', discipline_name: 'Kickboxing' },
        },
      ],
      count: 1,
      page: 1,
      page_size: 20,
      has_next: false,
      has_previous: false,
    })

    renderPage()

    await waitFor(() => expect(screen.getByText('Ana Perez')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Ver reservas' }))

    await waitFor(() =>
      expect(studentOverviewDetailsApi.reservations).toHaveBeenCalledWith(
        '42',
        expect.objectContaining({ page: 1, page_size: 20 }),
      ),
    )
    expect(getStudentOverview).toHaveBeenCalledTimes(1)
    expect(screen.getAllByText('Kick 19h').length).toBeGreaterThan(0)
  })
})
