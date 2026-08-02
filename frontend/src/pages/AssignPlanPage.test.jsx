import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  assignPlanToUser: vi.fn(),
  getPlans: vi.fn(),
  usersApi: { list: vi.fn() },
}))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin' } }),
}))

import { getPlans, usersApi } from '../api/client'
import AssignPlanPage from './AssignPlanPage'

beforeEach(() => {
  vi.clearAllMocks()
  usersApi.list.mockResolvedValue([])
  getPlans.mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
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
