import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  paymentsApi: { getAccount: vi.fn(), connect: vi.fn(), disconnect: vi.fn() },
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

  it('conectado: muestra el botón de desconectar y al confirmar desconecta y vuelve al estado desconectado', async () => {
    paymentsApi.getAccount.mockResolvedValue({
      provider: 'mercadopago', status: 'connected', provider_user_id: '123456789',
      is_sandbox: false, connected_at: '2026-07-05T14:30:00Z', token_expires_at: '2026-12-31T00:00:00Z',
    })
    paymentsApi.disconnect.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    renderAt()

    const trigger = await screen.findByRole('button', { name: /desconectar cuenta/i })
    await userEvent.click(trigger)

    // Confirmación con la advertencia explícita.
    expect(await screen.findByText(/dejarás de recibir pagos hasta reconectar/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /sí, desconectar/i }))

    await waitFor(() => expect(paymentsApi.disconnect).toHaveBeenCalled())
    // La respuesta del disconnect deja el estado "Aún no conectas".
    expect(await screen.findByText(/aún no conectas/i)).toBeInTheDocument()
  })

  it('conectado: al desconectar usa la respuesta del endpoint sin un segundo GET de estado', async () => {
    // Regresión: el estado desconectado se toma de la respuesta del POST /disconnect, NO de
    // un segundo GET /account que, si fallara, dejaría la UI mostrando "conectada" + un banner
    // de error contradictorio junto al de éxito.
    paymentsApi.getAccount.mockResolvedValue({
      provider: 'mercadopago', status: 'connected', provider_user_id: '123456789',
      is_sandbox: false, connected_at: '2026-07-05T14:30:00Z', token_expires_at: '2026-12-31T00:00:00Z',
    })
    paymentsApi.disconnect.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    renderAt()

    await userEvent.click(await screen.findByRole('button', { name: /desconectar cuenta/i }))
    await userEvent.click(await screen.findByRole('button', { name: /sí, desconectar/i }))

    await waitFor(() => expect(paymentsApi.disconnect).toHaveBeenCalled())
    expect(await screen.findByText(/aún no conectas/i)).toBeInTheDocument()
    expect(screen.queryByText('Cuenta conectada')).not.toBeInTheDocument()
    // Solo la llamada del montaje: el estado post-desconexión viene de la respuesta del POST.
    expect(paymentsApi.getAccount).toHaveBeenCalledTimes(1)
  })

  it('conectado: cancelar la confirmación NO desconecta', async () => {
    paymentsApi.getAccount.mockResolvedValue({
      provider: 'mercadopago', status: 'connected', provider_user_id: '123456789',
      is_sandbox: false, connected_at: '2026-07-05T14:30:00Z', token_expires_at: '2026-12-31T00:00:00Z',
    })
    renderAt()

    await userEvent.click(await screen.findByRole('button', { name: /desconectar cuenta/i }))
    await userEvent.click(await screen.findByRole('button', { name: /cancelar/i }))

    expect(paymentsApi.disconnect).not.toHaveBeenCalled()
    expect(screen.getByText('Cuenta conectada')).toBeInTheDocument()
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
