import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  trialWindowConfigApi: { get: vi.fn(), update: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 } }),
}))

import { trialWindowConfigApi } from '../api/client'
import GymAdminTrialWindowConfigPage from './GymAdminTrialWindowConfigPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminTrialWindowConfigPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  trialWindowConfigApi.get.mockResolvedValue({ trial_validity_days: 7 })
  trialWindowConfigApi.update.mockResolvedValue({ trial_validity_days: 14 })
})

describe('GymAdminTrialWindowConfigPage', () => {
  it('carga y guarda los dias de ventana de prueba', async () => {
    const user = userEvent.setup()
    renderPage()

    const input = await screen.findByLabelText('Días disponibles para reservar prueba')
    expect(input).toHaveValue(7)

    await user.clear(input)
    await user.type(input, '14')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() =>
      expect(trialWindowConfigApi.update).toHaveBeenCalledWith(7, {
        trial_validity_days: 14,
      }),
    )
    expect(await screen.findByText('Configuración guardada correctamente.')).toBeInTheDocument()
  })

  it('rechaza valores fuera de rango sin llamar al PUT', async () => {
    const user = userEvent.setup()
    renderPage()

    const input = await screen.findByLabelText('Días disponibles para reservar prueba')
    await user.clear(input)
    await user.type(input, '0')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/entero entre 1 y 366/i)).toBeInTheDocument()
    expect(trialWindowConfigApi.update).not.toHaveBeenCalled()
  })
})
