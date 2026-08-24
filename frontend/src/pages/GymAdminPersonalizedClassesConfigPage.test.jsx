import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const refreshMe = vi.fn()

vi.mock('../api/client', () => ({
  organizationsApi: {
    retrieve: vi.fn(),
    setPersonalizedClasses: vi.fn(),
  },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 }, refreshMe }),
}))

import { organizationsApi } from '../api/client'
import GymAdminPersonalizedClassesConfigPage from './GymAdminPersonalizedClassesConfigPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminPersonalizedClassesConfigPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  organizationsApi.retrieve.mockResolvedValue({ id: 7, personalized_classes_enabled: false })
  organizationsApi.setPersonalizedClasses.mockResolvedValue({ id: 7, personalized_classes_enabled: true })
  refreshMe.mockResolvedValue({ id: 9 })
})

describe('GymAdminPersonalizedClassesConfigPage', () => {
  it('carga, activa clases personalizadas y refresca la sesion', async () => {
    const user = userEvent.setup()
    renderPage()

    const checkbox = await screen.findByRole('checkbox', { name: /habilitar clases personalizadas/i })
    expect(checkbox).not.toBeChecked()

    await user.click(checkbox)
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(organizationsApi.setPersonalizedClasses).toHaveBeenCalledWith(7, true))
    await waitFor(() => expect(refreshMe).toHaveBeenCalled())
    expect(await screen.findByText('Configuracion guardada correctamente.')).toBeInTheDocument()
  })
})
