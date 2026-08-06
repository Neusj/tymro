import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  teacherPaymentConfigApi: { get: vi.fn(), update: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 } }),
}))

import { teacherPaymentConfigApi } from '../api/client'
import GymAdminTeacherPaymentConfigPage from './GymAdminTeacherPaymentConfigPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminTeacherPaymentConfigPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  teacherPaymentConfigApi.get.mockResolvedValue({ free_class_teacher_payment_value: 2000 })
  teacherPaymentConfigApi.update.mockResolvedValue({ free_class_teacher_payment_value: 5000 })
})

describe('GymAdminTeacherPaymentConfigPage — carga inicial', () => {
  it('carga el valor existente en el input', async () => {
    renderPage()

    const input = await screen.findByLabelText('Valor de clase gratis (para pago al profesor)')
    expect(input).toHaveValue(2000)
    expect(teacherPaymentConfigApi.get).toHaveBeenCalledWith(7)
  })
})

describe('GymAdminTeacherPaymentConfigPage — guardar (PUT)', () => {
  it('edita el valor y manda free_class_teacher_payment_value como número', async () => {
    renderPage()
    const input = await screen.findByLabelText('Valor de clase gratis (para pago al profesor)')
    const user = userEvent.setup()

    await user.clear(input)
    await user.type(input, '5000')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() =>
      expect(teacherPaymentConfigApi.update).toHaveBeenCalledWith(7, {
        free_class_teacher_payment_value: 5000,
      }),
    )
    expect(await screen.findByText('Configuración guardada correctamente.')).toBeInTheDocument()
  })

  it('rechaza un valor negativo sin llamar al PUT', async () => {
    renderPage()
    const input = await screen.findByLabelText('Valor de clase gratis (para pago al profesor)')
    const user = userEvent.setup()

    await user.clear(input)
    await user.type(input, '-5')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/número mayor o igual a 0/i)).toBeInTheDocument()
    expect(teacherPaymentConfigApi.update).not.toHaveBeenCalled()
  })

  it('si el backend responde 400, muestra el error real del backend', async () => {
    renderPage()
    await screen.findByLabelText('Valor de clase gratis (para pago al profesor)')
    const user = userEvent.setup()

    teacherPaymentConfigApi.update.mockRejectedValue({
      response: { data: { free_class_teacher_payment_value: ['Debe ser mayor o igual a 0.'] } },
    })

    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText('Debe ser mayor o igual a 0.')).toBeInTheDocument()
  })
})
