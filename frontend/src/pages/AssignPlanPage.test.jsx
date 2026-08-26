import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  assignPlanToUser: vi.fn(),
  getPlans: vi.fn(),
  quotePlanAssignment: vi.fn(),
  usersApi: { list: vi.fn(), retrieve: vi.fn() },
}))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin' } }),
}))

import { getPlans, quotePlanAssignment, usersApi } from '../api/client'
import AssignPlanPage from './AssignPlanPage'

beforeEach(() => {
  vi.clearAllMocks()
  usersApi.list.mockResolvedValue([])
  usersApi.retrieve.mockResolvedValue(null)
  getPlans.mockResolvedValue([])
  quotePlanAssignment.mockResolvedValue({
    plan_amount: '0.00',
    enrollment_fee_amount: '0.00',
    line_items_total: '0.00',
    total: '0.00',
    enrollment_fee_required: false,
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AssignPlanPage - buscador de alumnos', () => {
  it.each([
    ['nombre', 'Javier'],
    ['correo', 'javier@test.local'],
  ])('busca alumnos server-side por %s', async (_label, query) => {
    usersApi.list.mockResolvedValue([
      { id: 55, first_name: 'Javier', last_name: 'Neus', username: 'jneus', email: 'javier@test.local' },
    ])

    render(
      <MemoryRouter initialEntries={['/gym-admin/plans/assign?organization_id=9']}>
        <AssignPlanPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByLabelText('Alumno')).toBeEnabled())
    await userEvent.type(screen.getByLabelText('Alumno'), query)

    await waitFor(() =>
      expect(usersApi.list).toHaveBeenLastCalledWith({
        organization_id: '9',
        role: 'student,gym_admin',
        search: query,
        limit: 15,
      }),
    )
    expect(await screen.findByText('Javier Neus')).toBeInTheDocument()
    expect(screen.getByText('javier@test.local')).toBeInTheDocument()
  })

  it('no consulta alumnos con menos de dos caracteres', async () => {
    render(<MemoryRouter><AssignPlanPage /></MemoryRouter>)

    await waitFor(() => expect(screen.getByLabelText('Alumno')).toBeEnabled())
    await userEvent.type(screen.getByLabelText('Alumno'), 'J')

    expect(screen.getByText('Escribe al menos 2 caracteres.')).toBeInTheDocument()
    expect(usersApi.list).not.toHaveBeenCalled()
  })

  it('mantiene el alumno preseleccionado por user_id', async () => {
    usersApi.retrieve.mockResolvedValue({
      id: 7,
      first_name: 'Ana',
      last_name: 'Lopez',
      username: 'ana',
      email: 'ana@test.local',
    })

    render(
      <MemoryRouter initialEntries={['/gym-admin/plans/assign?user_id=7']}>
        <AssignPlanPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(usersApi.retrieve).toHaveBeenCalledWith('7'))
    expect(await screen.findByText('Ana Lopez')).toBeInTheDocument()
    expect(screen.getByText('ana@test.local')).toBeInTheDocument()
  })
})

describe('AssignPlanPage — fecha de inicio propuesta', () => {
  it('propone la fecha LOCAL, no la UTC, a las 21:30 de Chile', async () => {
    // Este campo se ENVÍA: el backend deriva end_date = start_date + duración, así que
    // proponer el día siguiente corría la ventana completa de la membresía.
    // 2026-07-31 01:30 UTC = 2026-07-30 21:30 en Santiago.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-07-31T01:30:00Z'))

    render(<MemoryRouter><AssignPlanPage /></MemoryRouter>)

    await waitFor(() => expect(screen.getByLabelText('Fecha inicio')).toHaveValue('2026-07-30'))
  })

  it('propone el día corriente cuando UTC y Chile coinciden en fecha', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-07-30T15:00:00Z'))

    render(<MemoryRouter><AssignPlanPage /></MemoryRouter>)

    await waitFor(() => expect(screen.getByLabelText('Fecha inicio')).toHaveValue('2026-07-30'))
  })
})
