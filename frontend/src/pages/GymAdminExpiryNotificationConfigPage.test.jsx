import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  expiryNotificationConfigApi: { get: vi.fn(), update: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 } }),
}))

import { expiryNotificationConfigApi } from '../api/client'
import GymAdminExpiryNotificationConfigPage from './GymAdminExpiryNotificationConfigPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminExpiryNotificationConfigPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  expiryNotificationConfigApi.get.mockResolvedValue({
    reminder_days_before: [10, 3],
    send_expired_notice: false,
  })
  expiryNotificationConfigApi.update.mockResolvedValue({
    reminder_days_before: [10, 3],
    send_expired_notice: false,
  })
})

describe('GymAdminExpiryNotificationConfigPage — carga inicial', () => {
  it('carga la config existente y pinta un chip por cada día', async () => {
    renderPage()

    expect(await screen.findByText('10 días')).toBeInTheDocument()
    expect(screen.getByText('3 días')).toBeInTheDocument()
    expect(expiryNotificationConfigApi.get).toHaveBeenCalledWith(7)
  })
})

describe('GymAdminExpiryNotificationConfigPage — agregar días (validación en la UI)', () => {
  it('agrega un valor válido como chip nuevo', async () => {
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    const input = screen.getByLabelText('Días de anticipación a agregar')
    await user.type(input, '5')
    await user.click(screen.getByRole('button', { name: 'Agregar' }))

    expect(await screen.findByText('5 días')).toBeInTheDocument()
  })

  it('rechaza un valor fuera de rango (0 o mayor a 365) sin agregarlo', async () => {
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    const input = screen.getByLabelText('Días de anticipación a agregar')
    await user.type(input, '400')
    await user.click(screen.getByRole('button', { name: 'Agregar' }))

    expect(await screen.findByText(/entero entre 1 y 365/i)).toBeInTheDocument()
    expect(screen.queryByText('400 días')).not.toBeInTheDocument()
  })

  it('rechaza un valor duplicado', async () => {
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    const input = screen.getByLabelText('Días de anticipación a agregar')
    await user.type(input, '10')
    await user.click(screen.getByRole('button', { name: 'Agregar' }))

    expect(await screen.findByText(/ya está en la lista/i)).toBeInTheDocument()
  })

  it('rechaza agregar un 11vo valor (tope de 10)', async () => {
    expiryNotificationConfigApi.get.mockResolvedValue({
      reminder_days_before: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      send_expired_notice: false,
    })
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    // El botón "Agregar" se deshabilita apenas se llega al tope.
    expect(screen.getByRole('button', { name: 'Agregar' })).toBeDisabled()
  })

  it('permite quitar un día ya agregado', async () => {
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Quitar 10 días' }))

    expect(screen.queryByText('10 días')).not.toBeInTheDocument()
    expect(screen.getByText('3 días')).toBeInTheDocument()
  })
})

describe('GymAdminExpiryNotificationConfigPage — guardar (PUT)', () => {
  it('manda reminder_days_before como lista de enteros y send_expired_notice como bool', async () => {
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    const input = screen.getByLabelText('Días de anticipación a agregar')
    await user.type(input, '1')
    await user.click(screen.getByRole('button', { name: 'Agregar' }))
    await screen.findByText('1 días')

    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() =>
      expect(expiryNotificationConfigApi.update).toHaveBeenCalledWith(7, {
        reminder_days_before: [10, 3, 1],
        send_expired_notice: true,
      }),
    )
    expect(await screen.findByText('Configuración guardada correctamente.')).toBeInTheDocument()
  })

  it('si el backend responde 400, muestra el error real del backend', async () => {
    renderPage()
    await screen.findByText('10 días')
    const user = userEvent.setup()

    expiryNotificationConfigApi.update.mockRejectedValue({
      response: { data: { reminder_days_before: ['Máximo 10 valores permitidos.'] } },
    })

    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText('Máximo 10 valores permitidos.')).toBeInTheDocument()
  })
})
