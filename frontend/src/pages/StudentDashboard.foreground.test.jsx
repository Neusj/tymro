import { render, waitFor } from '@testing-library/react'
import { act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  getMyPlan: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'stu', first_name: 'S', last_name: 'T' } }),
}))

import { getMyPlan } from '../api/client'
import StudentDashboard from './StudentDashboard'

function returnToForeground() {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  getMyPlan.mockResolvedValue({
    plan_name: 'Mensual', total_classes: 12, classes_used: 3,
    is_active: true, start_date: '2026-01-01', end_date: '2026-12-31',
  })
})

afterEach(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
})

describe('StudentDashboard — refresco al volver el foco', () => {
  it('re-llama getMyPlan cuando la PWA vuelve al foco', async () => {
    render(<MemoryRouter><StudentDashboard /></MemoryRouter>)

    // El fetch inicial del mount.
    await waitFor(() => expect(getMyPlan).toHaveBeenCalledTimes(1))

    returnToForeground()

    // La re-entrada al foco vuelve a pedir el plan.
    await waitFor(() => expect(getMyPlan).toHaveBeenCalledTimes(2))
  })
})
