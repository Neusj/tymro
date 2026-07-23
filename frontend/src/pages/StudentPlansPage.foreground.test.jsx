import { render, waitFor } from '@testing-library/react'
import { act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  getMyMemberships: vi.fn(),
  paymentsApi: { checkout: vi.fn() },
}))

import { getMyMemberships } from '../api/client'
import StudentPlansPage from './StudentPlansPage'

function returnToForeground() {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  getMyMemberships.mockResolvedValue([])
  // DataTable (renderizado por la página) usa matchMedia, que jsdom no implementa.
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
})

afterEach(() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
  delete window.matchMedia
})

describe('StudentPlansPage — refresco al volver el foco', () => {
  it('re-llama getMyMemberships cuando la PWA vuelve al foco', async () => {
    render(<MemoryRouter><StudentPlansPage /></MemoryRouter>)

    // El fetch inicial del mount (loadData).
    await waitFor(() => expect(getMyMemberships).toHaveBeenCalledTimes(1))

    returnToForeground()

    // La re-entrada al foco vuelve a cargar los planes.
    await waitFor(() => expect(getMyMemberships).toHaveBeenCalledTimes(2))
  })
})
