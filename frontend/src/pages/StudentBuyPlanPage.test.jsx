import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  getPlans: vi.fn(),
  paymentsApi: { checkout: vi.fn() },
}))

import { getPlans, paymentsApi } from '../api/client'
import StudentBuyPlanPage from './StudentBuyPlanPage'

const renderPage = () => render(<MemoryRouter><StudentBuyPlanPage /></MemoryRouter>)

let assignMock
beforeEach(() => {
  vi.clearAllMocks()
  assignMock = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { assign: assignMock, href: 'http://localhost/', pathname: '/' },
  })
})

const monthly = {
  id: 1, name: 'Plan Mensual', plan_type: 'monthly', price: 30000, discount_percentage: 0,
  total_classes: 12, unlimited_classes: false, duration_days: 30, is_public: true, is_active: true,
}
const discounted = {
  id: 2, name: 'Pack 8', plan_type: 'pack', price: 20000, discount_percentage: 25,
  total_classes: 8, unlimited_classes: false, duration_days: 60, is_public: true, is_active: true,
}
const trial = { id: 3, name: 'Clase de prueba', plan_type: 'trial', price: 0, is_public: true, is_active: true, total_classes: 1, duration_days: 1 }
const giftcard = { id: 4, name: 'Giftcard', plan_type: 'giftcard', price: 10000, is_public: true, is_active: true, total_classes: 1, duration_days: 30 }
const privatePlan = { id: 5, name: 'Interno', plan_type: 'monthly', price: 50000, is_public: false, is_active: true, total_classes: 20, duration_days: 30 }
const inactive = { id: 6, name: 'Viejo', plan_type: 'monthly', price: 50000, is_public: true, is_active: false, total_classes: 20, duration_days: 30 }

describe('StudentBuyPlanPage', () => {
  it('muestra solo planes comprables (excluye trial, giftcard, privados e inactivos)', async () => {
    getPlans.mockResolvedValue([monthly, discounted, trial, giftcard, privatePlan, inactive])
    renderPage()

    expect(await screen.findByText('Plan Mensual')).toBeInTheDocument()
    expect(screen.getByText('Pack 8')).toBeInTheDocument()
    expect(screen.queryByText('Clase de prueba')).not.toBeInTheDocument()
    expect(screen.queryByText('Giftcard')).not.toBeInTheDocument()
    expect(screen.queryByText('Interno')).not.toBeInTheDocument()
    expect(screen.queryByText('Viejo')).not.toBeInTheDocument()
  })

  it('aplica el descuento al precio mostrado', async () => {
    getPlans.mockResolvedValue([discounted])
    renderPage()

    // 20000 * (1 - 25%) = 15000; precio original tachado 20000; pill -25%
    expect(await screen.findAllByText('$15.000')).toHaveLength(2)
    expect(screen.getAllByText('$20.000')).toHaveLength(2)
    expect(screen.getByText((_, node) => node?.textContent === 'Descuento -25%')).toBeInTheDocument()
  })

  it('al pagar llama a checkout con planId y redirige al init_point', async () => {
    getPlans.mockResolvedValue([monthly])
    paymentsApi.checkout.mockResolvedValue({ transaction_id: 't1', redirect_url: 'https://mp/checkout/pref-1' })
    renderPage()

    await screen.findByText('Plan Mensual')
    await userEvent.click(screen.getByRole('button', { name: /pagar/i }))

    await waitFor(() => expect(paymentsApi.checkout).toHaveBeenCalledWith({ planId: 1 }))
    await waitFor(() => expect(assignMock).toHaveBeenCalledWith('https://mp/checkout/pref-1'))
  })

  it('muestra un mensaje amable cuando el gym no tiene MP (409)', async () => {
    getPlans.mockResolvedValue([monthly])
    paymentsApi.checkout.mockRejectedValue({ response: { status: 409, data: { detail: 'no conectado' } } })
    renderPage()

    await screen.findByText('Plan Mensual')
    await userEvent.click(screen.getByRole('button', { name: /pagar/i }))

    expect(await screen.findByText(/aún no habilitó pagos en línea/i)).toBeInTheDocument()
    expect(assignMock).not.toHaveBeenCalled()
  })

  it('muestra estado vacío cuando no hay planes comprables', async () => {
    getPlans.mockResolvedValue([trial, giftcard])
    renderPage()

    expect(await screen.findByText(/No hay planes disponibles para comprar/i)).toBeInTheDocument()
  })
})
