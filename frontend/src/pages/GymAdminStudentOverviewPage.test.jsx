import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  getStudentOverview: vi.fn(),
  usersApi: { list: vi.fn() },
}))

import { getStudentOverview, usersApi } from '../api/client'
import GymAdminStudentOverviewPage from './GymAdminStudentOverviewPage'

const EMPTY_SECTION = { items: [], limit: 20, has_more: false }

function overview(overrides = {}) {
  return {
    student: {
      id: 42, username: 'ana', name: 'Ana Perez', email: 'ana@test.local',
      phone: '', role: 'student', is_active: true, branch_id: null, branch_name: 'Sede Centro',
    },
    memberships: [],
    consumption: EMPTY_SECTION,
    attendance: EMPTY_SECTION,
    reservations: EMPTY_SECTION,
    recurring_enrollments: [],
    ...overrides,
  }
}

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
    days_to_expiry: 20,
    expiry_alert_level: 'safe',
    expiry_alert_message: '20 dias vigentes',
    payment_status: 'paid',
    enrollment_fee_status: { status: 'waived' },
    is_active: true,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  usersApi.list.mockResolvedValue([])
  // KpiStrip usa `useMediaQuery`, que llama a `window.matchMedia` (no lo provee jsdom).
  // Mismo mock que ya usa GymAdminPlanMembershipsPage.test.jsx.
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

function renderPage(initialEntry = '/gym-admin/students/overview?student_id=42') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <GymAdminStudentOverviewPage />
    </MemoryRouter>,
  )
}

describe('GymAdminStudentOverviewPage', () => {
  it('renderiza la membresía con su estado y estado de pago, tal cual los manda el backend', async () => {
    getStudentOverview.mockResolvedValue(overview({ memberships: [membership()] }))

    renderPage()

    await waitFor(() => expect(screen.getByText('Ana Perez')).toBeInTheDocument())
    expect(screen.getByText('Pack 10')).toBeInTheDocument()
    expect(screen.getByText('Vigente')).toBeInTheDocument()
    expect(screen.getByText('Pagado')).toBeInTheDocument()
    // El endpoint se llamó con el id que traía la URL, no uno inventado por el front.
    expect(getStudentOverview).toHaveBeenCalledWith('42', expect.any(Object))
  })

  it('respeta el vacío: cada sección sin filas muestra su EmptyState, sin reventar', async () => {
    getStudentOverview.mockResolvedValue(overview())

    renderPage()

    await waitFor(() => expect(screen.getByText('Ana Perez')).toBeInTheDocument())
    expect(screen.getByText('Sin membresías')).toBeInTheDocument()
    expect(screen.getByText('Sin recurrencias')).toBeInTheDocument()
    expect(screen.getByText('Sin consumo')).toBeInTheDocument()
    expect(screen.getByText('Sin asistencia')).toBeInTheDocument()
    expect(screen.getByText('Sin reservas')).toBeInTheDocument()
  })

  it('sin alumno seleccionado no llama al endpoint y muestra el estado vacío inicial', async () => {
    renderPage('/gym-admin/students/overview')

    await waitFor(() => expect(screen.getByText('Sin alumno seleccionado')).toBeInTheDocument())
    expect(getStudentOverview).not.toHaveBeenCalled()
  })

  it('muestra el error del backend si la carga falla, sin dejar la pantalla en blanco', async () => {
    getStudentOverview.mockRejectedValue({ response: { data: { detail: 'No encontrado.' } } })

    renderPage()

    await waitFor(() => expect(screen.getByText('No encontrado.')).toBeInTheDocument())
  })

  it('el botón "Ver más" pide el siguiente lote de consumo con un límite mayor', async () => {
    // `has_more=true` implica que YA vino el tope de filas (`_paged` en el backend nunca
    // publica `has_more` sin `items` llenos hasta el límite) — un `items: []` con
    // `has_more: true` es una combinación que el backend real no produce.
    const consumptionItem = {
      id: 1, consumed_at: '2026-07-01T10:00:00Z', branch_name: 'Sede', plan_name: 'Pack 10',
      class: { id: 9, name: 'Clase', start_datetime: '2026-07-01T09:00:00Z', end_datetime: '2026-07-01T10:00:00Z', status: 'completed', discipline_name: null, teacher_name: null },
    }
    getStudentOverview.mockResolvedValue(
      overview({ consumption: { items: [consumptionItem], limit: 1, has_more: true } }),
    )

    renderPage()

    const button = await screen.findByRole('button', { name: 'Ver más' })
    getStudentOverview.mockResolvedValue(overview())
    fireEvent.click(button)

    await waitFor(() =>
      expect(getStudentOverview).toHaveBeenLastCalledWith(
        '42',
        expect.objectContaining({ consumption_limit: 40 }),
      ),
    )
  })
})
