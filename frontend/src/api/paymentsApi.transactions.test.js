import { describe, it, expect, vi, beforeEach } from 'vitest'

// vi.mock() se hoistea sobre las declaraciones const; getMock debe crearse
// vía vi.hoisted() para evitar "Cannot access 'getMock' before initialization".
const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }))
// Mock completo de axios: client.js hace axios.create() (x2) y api.interceptors.*.use()
// al cargar el módulo; defaults está para blindar setAuthToken si algo lo tocara.
vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: getMock,
      post: vi.fn(),
      defaults: { headers: { common: {} } },
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    }),
  },
}))

import { paymentsApi } from './client'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('paymentsApi.listTransactions', () => {
  it('envía page/page_size y filtros, y devuelve data', async () => {
    getMock.mockResolvedValue({ data: { count: 0, results: [] } })

    const result = await paymentsApi.listTransactions({
      page: 2, pageSize: 10, status: 'approved', dateFrom: '2026-06-01', dateTo: '2026-06-30',
    })

    expect(getMock).toHaveBeenCalledWith('/payments/transactions/', {
      params: { page: 2, page_size: 10, status: 'approved', date_from: '2026-06-01', date_to: '2026-06-30' },
    })
    expect(result).toEqual({ count: 0, results: [] })
  })

  it('omite filtros vacíos', async () => {
    getMock.mockResolvedValue({ data: { count: 0, results: [] } })

    await paymentsApi.listTransactions({ page: 1, pageSize: 25 })

    expect(getMock).toHaveBeenCalledWith('/payments/transactions/', {
      params: { page: 1, page_size: 25 },
    })
  })
})
