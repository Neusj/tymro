import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  paymentsApi: { getAccount: vi.fn(), connect: vi.fn() },
}))

import { paymentsApi } from '../api/client'
import GymAdminPaymentsSettingsPage from './GymAdminPaymentsSettingsPage'

const renderAt = (search = '') =>
  render(
    <MemoryRouter initialEntries={[`/ajustes/pagos${search}`]}>
      <GymAdminPaymentsSettingsPage />
    </MemoryRouter>,
  )

let assignMock
beforeEach(() => {
  vi.clearAllMocks()
  assignMock = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { assign: assignMock, href: 'http://localhost/', pathname: '/ajustes/pagos' },
  })
})

describe('GymAdminPaymentsSettingsPage', () => {
  it('desconectado: muestra el CTA de conexión y al pulsar inicia OAuth y redirige', async () => {
    paymentsApi.getAccount.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    paymentsApi.connect.mockResolvedValue({ authorization_url: 'https://auth.mp/authorize?x=1' })
    renderAt()

    const btn = await screen.findByRole('button', { name: /conectar con mercadopago/i })
    await userEvent.click(btn)

    await waitFor(() => expect(paymentsApi.connect).toHaveBeenCalled())
    await waitFor(() => expect(assignMock).toHaveBeenCalledWith('https://auth.mp/authorize?x=1'))
  })

  it('conectado: muestra la cuenta cobradora y el badge de modo prueba', async () => {
    paymentsApi.getAccount.mockResolvedValue({
      provider: 'mercadopago', status: 'connected', provider_user_id: '123456789',
      is_sandbox: true, connected_at: '2026-07-05T14:30:00Z', token_expires_at: '2026-12-31T00:00:00Z',
    })
    renderAt()

    expect(await screen.findByText('Cuenta conectada')).toBeInTheDocument()
    expect(screen.getByText('123456789')).toBeInTheDocument()
    expect(screen.getByText('Modo prueba')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reconectar/i })).toBeInTheDocument()
  })

  it('banner de éxito cuando el callback vuelve con connected=1', async () => {
    paymentsApi.getAccount.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    renderAt('?connected=1')

    expect(await screen.findByText(/conectada correctamente/i)).toBeInTheDocument()
  })

  it('banner de error cuando el state OAuth expiró (connected=0&error=state)', async () => {
    paymentsApi.getAccount.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    renderAt('?connected=0&error=state')

    expect(await screen.findByText(/El enlace de conexión expiró/i)).toBeInTheDocument()
  })
})
