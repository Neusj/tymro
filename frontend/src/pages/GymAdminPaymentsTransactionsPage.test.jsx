import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  paymentsApi: { listTransactions: vi.fn() },
}))

import { paymentsApi } from '../api/client'
import GymAdminPaymentsTransactionsPage from './GymAdminPaymentsTransactionsPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/pagos/transacciones']}>
      <GymAdminPaymentsTransactionsPage />
    </MemoryRouter>,
  )

const row = (over = {}) => ({
  id: 'tx-1', created_at: '2026-06-15T14:30:00Z', processed_at: null,
  status: 'approved', status_detail: null,
  amount: '20000.00', plan_amount: '20000.00', enrollment_fee_amount: '0.00', currency: 'CLP',
  student_name: 'Ana Pérez', student_email: 'ana@gym.cl', student_phone: '+56911111111',
  plan_name: 'Mensual', concept: 'Plan: Mensual', line_items: [],
  activated_student_plan: true, student_plan: 5,
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('GymAdminPaymentsTransactionsPage', () => {
  it('renderiza filas con datos del alumno y badge de estado', async () => {
    paymentsApi.listTransactions.mockResolvedValue({ count: 1, next: null, previous: null, results: [row()] })
    renderPage()

    expect(await screen.findByText('Ana Pérez')).toBeInTheDocument()
    expect(screen.getByText('ana@gym.cl')).toBeInTheDocument()
    // Contrato #12: la celda "Concepto" ya NO es el string legacy a secas ("Plan: Mensual").
    // Ahora es un desglose armado en el front a partir de plan_amount/enrollment_fee_amount/
    // line_items, así que la línea del plan trae el monto pegado.
    expect(screen.getByText('Plan: Mensual — $20.000')).toBeInTheDocument()
    expect(screen.getByText(/aprobado/i, { selector: 'span' })).toBeInTheDocument()
  })

  it('el desglose muestra matrícula y conceptos adicionales (line_items) además del plan', async () => {
    paymentsApi.listTransactions.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [row({
        enrollment_fee_amount: '5000.00',
        line_items: [
          { id: 1, concept: 'Pesas', amount: '3000.00' },
          { id: 2, concept: 'Toalla', amount: '2000.00' },
        ],
      })],
    })
    renderPage()

    expect(await screen.findByText('Plan: Mensual — $20.000')).toBeInTheDocument()
    expect(screen.getByText('Matrícula — $5.000')).toBeInTheDocument()
    expect(screen.getByText('Pesas — $3.000')).toBeInTheDocument()
    expect(screen.getByText('Toalla — $2.000')).toBeInTheDocument()
  })

  it('sin plan_amount/enrollment_fee_amount/line_items cae al concept legacy', async () => {
    paymentsApi.listTransactions.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [row({ plan_amount: '0.00', enrollment_fee_amount: '0.00', line_items: [], concept: '—' })],
    })
    renderPage()

    expect(await screen.findByText('Ana Pérez')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('muestra estado vacío cuando no hay transacciones', async () => {
    paymentsApi.listTransactions.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    renderPage()

    expect(await screen.findByText(/sin transacciones/i)).toBeInTheDocument()
  })

  it('el filtro de estado dispara un refetch con el status elegido y resetea la página', async () => {
    paymentsApi.listTransactions.mockResolvedValue({ count: 60, next: 'x', previous: null, results: [row()] })
    renderPage()

    await waitFor(() => expect(paymentsApi.listTransactions).toHaveBeenCalled())

    const next = await screen.findByRole('button', { name: /siguiente/i })
    await userEvent.click(next)

    await waitFor(() =>
      expect(paymentsApi.listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
      ),
    )

    const select = screen.getByLabelText(/estado/i)
    await userEvent.selectOptions(select, 'approved')

    await waitFor(() =>
      expect(paymentsApi.listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'approved', page: 1 }),
      ),
    )
  })

  it('cambiar de página llama a la API con el page correcto', async () => {
    paymentsApi.listTransactions.mockResolvedValue({
      count: 30, next: 'x', previous: null, results: [row()],
    })
    renderPage()

    await waitFor(() => expect(paymentsApi.listTransactions).toHaveBeenCalled())
    const next = await screen.findByRole('button', { name: /siguiente/i })
    await userEvent.click(next)

    await waitFor(() =>
      expect(paymentsApi.listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
      ),
    )
  })
})
