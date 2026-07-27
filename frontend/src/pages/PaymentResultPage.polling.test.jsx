import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'

vi.mock('../api/client', () => ({
  paymentsApi: { transactionStatus: vi.fn() },
}))

import { paymentsApi } from '../api/client'
import PaymentResultPage from './PaymentResultPage'

// Literales a mano, iguales a los de la página (MAX_POLLS / POLL_MS). Se
// escriben acá en vez de importarlos para que el test no espeje la constante
// que está verificando.
const POLL_MS = 3000
const MAX_POLLS = 8

// Un timeout de axios: code ECONNABORTED y SIN `response` (nunca hubo respuesta).
// Es el error que ahora llega a los 10s en vez de colgarse para siempre.
const timeoutError = () =>
  new axios.AxiosError(
    'timeout of 10000ms exceeded',
    'ECONNABORTED',
    { url: '/payments/transactions/abc/status/', timeout: 10000 },
    {},
  )

const pending = { id: 'abc', status: 'pending', status_detail: null, amount: '30000', currency: 'CLP' }
const approved = { id: 'abc', status: 'approved', status_detail: 'accredited', amount: '30000', currency: 'CLP' }

const CONFIRMING = /estamos confirmando tu pago/i

const renderAt = (search) =>
  render(
    <MemoryRouter initialEntries={[`/pagos/resultado${search}`]}>
      <PaymentResultPage />
    </MemoryRouter>,
  )

// Deja resolver las promesas ya encoladas sin avanzar el reloj.
const settle = async () => {
  await act(async () => {
    await Promise.resolve()
  })
}

// Avanza hasta el siguiente poll agendado y deja que resuelva.
const nextPoll = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_MS)
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('PaymentResultPage: resiliencia del polling', () => {
  it('un poll que falla por timeout no corta la cadena: el siguiente poll ocurre', async () => {
    paymentsApi.transactionStatus
      .mockResolvedValueOnce(pending) // carga inicial
      .mockRejectedValueOnce(timeoutError()) // poll 1: antes mataba la cadena entera
      .mockResolvedValueOnce(approved) // poll 2: solo ocurre si la cadena sobrevivió

    renderAt('?tx=abc')
    await settle()
    expect(screen.getByText('Pago en proceso')).toBeInTheDocument()
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(1)

    await nextPoll()
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(2)

    await nextPoll()
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(3)
    expect(screen.getByText('¡Pago aprobado!')).toBeInTheDocument()
  })

  it('al agotar los polls sin estado final informa que se está confirmando, sin spinner infinito', async () => {
    paymentsApi.transactionStatus.mockResolvedValue(pending)

    renderAt('?tx=abc')
    await settle()

    for (let i = 0; i < MAX_POLLS; i += 1) {
      await nextPoll()
    }

    // 1 carga inicial + MAX_POLLS reintentos, y ni uno más.
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(MAX_POLLS + 1)
    expect(screen.getByText(CONFIRMING)).toBeInTheDocument()
    expect(screen.queryByText(/verificando la confirmación/i)).not.toBeInTheDocument()

    await nextPoll()
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(MAX_POLLS + 1)
  })

  it('si todos los polls fallan por timeout informa que se está confirmando y no culpa al alumno', async () => {
    paymentsApi.transactionStatus.mockRejectedValue(timeoutError())

    renderAt('?tx=abc')
    await settle()

    for (let i = 0; i < MAX_POLLS; i += 1) {
      await nextPoll()
    }

    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(MAX_POLLS + 1)
    expect(screen.getByText(CONFIRMING)).toBeInTheDocument()
    expect(screen.queryByText(/no pudimos mostrar el pago/i)).not.toBeInTheDocument()
  })

  it('un 404 es definitivo: no se reintenta ni se promete una confirmación que no existe', async () => {
    const notFound = new axios.AxiosError('Request failed with status code 404', 'ERR_BAD_REQUEST', {}, {}, {
      data: { detail: 'No encontrado.' },
      status: 404,
      statusText: 'Not Found',
      headers: {},
      config: {},
    })
    paymentsApi.transactionStatus.mockRejectedValue(notFound)

    renderAt('?tx=zzz')
    await settle()

    expect(screen.getByText('No pudimos mostrar el pago')).toBeInTheDocument()

    await nextPoll()
    await nextPoll()
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(CONFIRMING)).not.toBeInTheDocument()
  })

  it('si el pago se aprueba antes de agotar los polls muestra el éxito y deja de consultar', async () => {
    paymentsApi.transactionStatus
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(approved)

    renderAt('?tx=abc')
    await settle()

    await nextPoll()
    expect(screen.getByText('¡Pago aprobado!')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /ver mis planes/i })).toBeInTheDocument()

    // Estado terminal: la cadena se detiene, no sigue consultando.
    await nextPoll()
    await nextPoll()
    expect(paymentsApi.transactionStatus).toHaveBeenCalledTimes(2)
    expect(screen.queryByText(CONFIRMING)).not.toBeInTheDocument()
  })
})
