import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La página carga sucursales al montar (loadData) y, por sucursal, la sección "Cuenta de
// pagos propia" usa paymentsApi con branchId — mismo cliente que Ajustes → Pagos, con el
// parámetro extra.
vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
  paymentsApi: { getAccount: vi.fn(), connect: vi.fn(), disconnect: vi.fn() },
}))

let mockRole = 'gym_admin'
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}))

import { branchesApi, paymentsApi } from '../api/client'
import GymAdminBranchesPage from './GymAdminBranchesPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminBranchesPage />
    </MemoryRouter>,
  )
}

const branchSede = { id: 1, name: 'Sede Centro', code: 'CTR', address: 'Av. Siempre Viva 123', primary_color: '', is_active: true }
const branchInactiva = { id: 2, name: 'Sede Vieja', code: 'OLD', address: '', primary_color: '', is_active: false }

let assignMock
beforeEach(() => {
  vi.clearAllMocks()
  mockRole = 'gym_admin'
  branchesApi.list.mockResolvedValue([branchSede, branchInactiva])
  assignMock = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { assign: assignMock, href: 'http://localhost/', pathname: '/gym-admin/branches' },
  })
  // DataTable consulta matchMedia al montar; jsdom no lo implementa (mismo patrón que
  // GymAdminClassTemplatesPage.test.jsx).
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'),
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
})

afterEach(() => {
  delete window.matchMedia
})

describe('GymAdminBranchesPage — cuentas de pago por sucursal', () => {
  it('lista solo sucursales activas en la sección de cuentas de pago, colapsada y sin llamar a getAccount', async () => {
    renderPage()

    await waitFor(() => expect(branchesApi.list).toHaveBeenCalled())
    expect(await screen.findByText('Cuentas de pago por sucursal')).toBeInTheDocument()

    // La sede activa aparece en la sección de cuentas propias...
    expect(screen.getAllByText('Sede Centro').length).toBeGreaterThan(0)
    // ...la inactiva sigue en la tabla general (dentro del CRUD) pero no se ofrece connect.
    // La tabla general también renderiza su nombre, así que solo verificamos que NO haya
    // un toggle "Cuenta de pagos propia" para ella.
    const toggles = screen.getAllByRole('button', { name: /cuenta de pagos propia/i })
    expect(toggles).toHaveLength(1)

    // Colapsada: no se consulta el estado hasta abrir.
    expect(paymentsApi.getAccount).not.toHaveBeenCalled()
  })

  it('sin cuenta: al expandir consulta el estado con branch_id y muestra el checkbox + botón de conectar', async () => {
    paymentsApi.getAccount.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    paymentsApi.connect.mockResolvedValue({ authorization_url: 'https://auth.mp/authorize?branch=1' })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /cuenta de pagos propia/i }))

    await waitFor(() => expect(paymentsApi.getAccount).toHaveBeenCalledWith({ branchId: 1 }))
    expect(await screen.findByText(/cobra sus membresías con la cuenta principal/i)).toBeInTheDocument()

    // El botón de conectar no aparece hasta tildar el checkbox.
    expect(screen.queryByRole('button', { name: /^conectar mercadopago$/i })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: /usar cuenta propia/i }))

    const connectBtn = await screen.findByRole('button', { name: /^conectar mercadopago$/i })
    await userEvent.click(connectBtn)

    await waitFor(() => expect(paymentsApi.connect).toHaveBeenCalledWith({ branchId: 1 }))
    await waitFor(() => expect(assignMock).toHaveBeenCalledWith('https://auth.mp/authorize?branch=1'))
  })

  it('409 al conectar: muestra el detail del backend y un CTA a Ajustes → Pagos', async () => {
    paymentsApi.getAccount.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago' })
    paymentsApi.connect.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Conectá primero la cuenta principal del gimnasio antes de configurar una cuenta por sucursal.' },
      },
    })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /cuenta de pagos propia/i }))
    await screen.findByText(/cobra sus membresías con la cuenta principal/i)
    await userEvent.click(screen.getByRole('checkbox', { name: /usar cuenta propia/i }))
    await userEvent.click(await screen.findByRole('button', { name: /^conectar mercadopago$/i }))

    expect(await screen.findByText(/conectá primero la cuenta principal del gimnasio/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /ir a ajustes → pagos/i })).toHaveAttribute('href', '/ajustes/pagos')
    expect(assignMock).not.toHaveBeenCalled()
  })

  it('cuenta conectada: muestra la cuenta cobradora y permite desconectar (con confirmación, pasando branch_id)', async () => {
    paymentsApi.getAccount.mockResolvedValue({
      provider: 'mercadopago', status: 'connected', provider_user_id: '987654321',
      is_sandbox: false, connected_at: '2026-07-05T14:30:00Z', token_expires_at: '2026-12-31T00:00:00Z', branch: 1,
    })
    paymentsApi.disconnect.mockResolvedValue({ status: 'disconnected', provider: 'mercadopago', provider_user_id: '987654321', branch: 1 })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /cuenta de pagos propia/i }))
    expect(await screen.findByText('987654321')).toBeInTheDocument()

    await userEvent.click(await screen.findByRole('button', { name: /^desconectar$/i }))
    expect(await screen.findByText(/dejará de cobrar con su cuenta propia/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /sí, desconectar/i }))

    await waitFor(() => expect(paymentsApi.disconnect).toHaveBeenCalledWith({ branchId: 1 }))
    expect(await screen.findByText(/la cuenta propia de esta sucursal está desconectada/i)).toBeInTheDocument()
  })

  it('manager: la sección de cuentas de pago no se muestra (misma gate que Editar/Eliminar)', async () => {
    mockRole = 'manager'
    renderPage()

    await waitFor(() => expect(branchesApi.list).toHaveBeenCalled())
    expect(screen.queryByText('Cuentas de pago por sucursal')).not.toBeInTheDocument()
  })
})
