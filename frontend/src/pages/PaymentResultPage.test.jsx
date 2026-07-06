import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  paymentsApi: { transactionStatus: vi.fn() },
}))

import { paymentsApi } from '../api/client'
import PaymentResultPage from './PaymentResultPage'

const renderAt = (search) =>
  render(
    <MemoryRouter initialEntries={[`/pagos/resultado${search}`]}>
      <PaymentResultPage />
    </MemoryRouter>,
  )

const WEBHOOK_NOTE = /la activación de tu plan la confirma mercadopago mediante una notificación automática/i

beforeEach(() => {
  // resetAllMocks (no clearAllMocks): además de las llamadas, resetea las
  // implementaciones y las colas de mockResolvedValueOnce entre tests, para que
  // un valor encolado en un test no se filtre al siguiente.
  vi.resetAllMocks()
})

describe('PaymentResultPage', () => {
  it('sin tx muestra error de referencia y no llama al backend', async () => {
    renderAt('')
    expect(await screen.findByText(/No encontramos la referencia del pago/i)).toBeInTheDocument()
    expect(paymentsApi.transactionStatus).not.toHaveBeenCalled()
  })

  it('estado approved muestra éxito, monto, nota de webhook y link a mis planes', async () => {
    paymentsApi.transactionStatus.mockResolvedValue({
      id: 'abc', status: 'approved', status_detail: 'accredited', amount: '30000', currency: 'CLP',
    })
    renderAt('?tx=abc')

    expect(await screen.findByText('¡Pago aprobado!')).toBeInTheDocument()
    expect(screen.getByText('$30.000')).toBeInTheDocument()
    expect(screen.getByText(WEBHOOK_NOTE)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /ver mis planes/i })).toBeInTheDocument()
  })

  it('estado rejected muestra rechazo, el motivo y botón de reintento', async () => {
    paymentsApi.transactionStatus.mockResolvedValue({
      id: 'abc', status: 'rejected', status_detail: 'cc_rejected_insufficient_amount', amount: '30000', currency: 'CLP',
    })
    renderAt('?tx=abc')

    expect(await screen.findByText('Pago rechazado')).toBeInTheDocument()
    expect(screen.getByText(/cc_rejected_insufficient_amount/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /volver a intentar/i })).toBeInTheDocument()
  })

  it('estado pending muestra "en proceso", botón Actualizar y la nota de webhook', async () => {
    paymentsApi.transactionStatus.mockResolvedValue({
      id: 'abc', status: 'pending', status_detail: null, amount: '30000', currency: 'CLP',
    })
    renderAt('?tx=abc')

    expect(await screen.findByText('Pago en proceso')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /actualizar/i })).toBeInTheDocument()
    expect(screen.getByText(WEBHOOK_NOTE)).toBeInTheDocument()
  })

  it('al Actualizar re-consulta y pasa de pending a approved (estado terminal)', async () => {
    paymentsApi.transactionStatus
      .mockResolvedValueOnce({ id: 'abc', status: 'pending', amount: '30000', currency: 'CLP' })
      .mockResolvedValueOnce({ id: 'abc', status: 'approved', amount: '30000', currency: 'CLP' })
    renderAt('?tx=abc')

    await screen.findByText('Pago en proceso')
    await userEvent.click(screen.getByRole('button', { name: /actualizar/i }))

    expect(await screen.findByText('¡Pago aprobado!')).toBeInTheDocument()
  })

  it('un 404 muestra que el pago no se encontró', async () => {
    paymentsApi.transactionStatus.mockRejectedValue({ response: { status: 404 } })
    renderAt('?tx=zzz')

    // Encabezado exacto (el mensaje también contiene "No encontramos este pago",
    // así que se consulta el heading para evitar múltiples coincidencias).
    expect(await screen.findByText('No pudimos mostrar el pago')).toBeInTheDocument()
    expect(screen.getByText(/no encontramos este pago, o no te pertenece/i)).toBeInTheDocument()
  })
})
