import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  enrollmentFeeConfigApi: { get: vi.fn(), update: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 } }),
}))

import { enrollmentFeeConfigApi } from '../api/client'
import GymAdminEnrollmentFeeConfigPage from './GymAdminEnrollmentFeeConfigPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminEnrollmentFeeConfigPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  enrollmentFeeConfigApi.get.mockResolvedValue({ annual_enrollment_fee: '15000.00' })
  enrollmentFeeConfigApi.update.mockResolvedValue({ annual_enrollment_fee: '20000.00' })
})

describe('GymAdminEnrollmentFeeConfigPage', () => {
  it('carga y guarda el monto de matricula anual', async () => {
    renderPage()
    const input = await screen.findByLabelText('Matricula anual')
    const user = userEvent.setup()

    expect(input).toHaveValue(15000)
    expect(enrollmentFeeConfigApi.get).toHaveBeenCalledWith(7)

    await user.clear(input)
    await user.type(input, '20000')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() =>
      expect(enrollmentFeeConfigApi.update).toHaveBeenCalledWith(7, {
        annual_enrollment_fee: 20000,
      }),
    )
    expect(await screen.findByText('Configuracion guardada correctamente.')).toBeInTheDocument()
  })

  it('rechaza valores negativos sin llamar al backend', async () => {
    renderPage()
    const input = await screen.findByLabelText('Matricula anual')
    const user = userEvent.setup()

    await user.clear(input)
    await user.type(input, '-1')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/numero mayor o igual a 0/i)).toBeInTheDocument()
    expect(enrollmentFeeConfigApi.update).not.toHaveBeenCalled()
  })
})
