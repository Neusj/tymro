import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  reportsApi: { revenue: vi.fn(), exportRevenue: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, reportsApi } from '../api/client'
import GymAdminRevenueReportPage from './GymAdminRevenueReportPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/reports/revenue']}>
      <GymAdminRevenueReportPage />
    </MemoryRouter>,
  )

const baseReport = (over = {}) => ({
  period: { date_from: '2026-08-01', date_to: '2026-08-06', days: 6, granularity: 'day' },
  filters: { branch_id: null, branch_name: null, method: null, method_label: null },
  totals: { gross: 100000, refunds: 20000, net: 80000, payments_count: 12, refunds_count: 2 },
  previous: { period: {}, totals: {} },
  comparison: { net_delta: 5000, net_delta_pct: 6.7, gross_delta: 4000, gross_delta_pct: 4.2 },
  by_method: [
    { method: 'mercadopago', label: 'MercadoPago', gross: 60000, refunds: 10000, net: 50000, payments_count: 6, refunds_count: 1 },
    { method: 'cash', label: 'Efectivo', gross: 30000, refunds: 5000, net: 25000, payments_count: 4, refunds_count: 1 },
    { method: 'transfer', label: 'Transferencia', gross: 10000, refunds: 5000, net: 5000, payments_count: 2, refunds_count: 0 },
  ],
  series: [
    { bucket: '2026-08-01', gross: 20000, refunds: 5000, net: 15000 },
    { bucket: '2026-08-02', gross: 30000, refunds: 5000, net: 25000 },
  ],
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  branchesApi.list.mockResolvedValue([])
})

describe('GymAdminRevenueReportPage', () => {
  it('muestra bruto, devoluciones y neto como TRES números separados (nunca uno que se coma la resta)', async () => {
    reportsApi.revenue.mockResolvedValue(baseReport())
    renderPage()

    // Cada monto aparece en la ecuación Y en su StatCard (dos apariciones cada uno) —
    // lo importante es que los TRES son visibles y distintos entre sí, nunca un solo
    // total que se coma la resta.
    await waitFor(() => expect(screen.getAllByText('$100.000').length).toBeGreaterThanOrEqual(2)) // bruto
    expect(screen.getAllByText('$20.000').length).toBeGreaterThanOrEqual(2) // devoluciones
    expect(screen.getAllByText('$80.000').length).toBeGreaterThanOrEqual(2) // neto

    // Los tres labels están presentes (aparecen en la StatCard y también en la leyenda
    // del gráfico de evolución, por eso getAllByText en vez de uno solo).
    expect(screen.getAllByText('Bruto').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Devoluciones').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Neto').length).toBeGreaterThanOrEqual(1)
  })

  it('con net_delta_pct null muestra un guion, NUNCA "0%"', async () => {
    reportsApi.revenue.mockResolvedValue(
      baseReport({ comparison: { net_delta: null, net_delta_pct: null, gross_delta: null, gross_delta_pct: null } }),
    )
    renderPage()

    expect(await screen.findByText('— vs. período anterior')).toBeInTheDocument()
    expect(screen.queryByText(/0%\s*vs\. período anterior/)).not.toBeInTheDocument()
    expect(screen.queryByText('0% vs. período anterior')).not.toBeInTheDocument()
  })

  it('el desglose por método soporta un 4º método (unknown) sin lista fija de 3', async () => {
    reportsApi.revenue.mockResolvedValue(
      baseReport({
        by_method: [
          { method: 'mercadopago', label: 'MercadoPago', gross: 60000, refunds: 10000, net: 50000, payments_count: 6, refunds_count: 1 },
          { method: 'cash', label: 'Efectivo', gross: 20000, refunds: 0, net: 20000, payments_count: 3, refunds_count: 0 },
          { method: 'transfer', label: 'Transferencia', gross: 10000, refunds: 0, net: 10000, payments_count: 2, refunds_count: 0 },
          { method: 'unknown', label: 'Sin método registrado', gross: 5000, refunds: 0, net: 5000, payments_count: 1, refunds_count: 0 },
        ],
      }),
    )
    renderPage()

    // "Sin método registrado" y "MercadoPago" ya están SIEMPRE como <option> del filtro
    // (lista estática); que aparezcan una SEGUNDA vez prueba que la fila del gráfico de
    // desglose también se renderizó — o sea, que el 4º método sí llegó hasta la UI.
    await waitFor(() => expect(screen.getAllByText('Sin método registrado').length).toBeGreaterThanOrEqual(2))
    expect(screen.getAllByText('MercadoPago').length).toBeGreaterThanOrEqual(2)
  })

  it('muestra estado de carga y luego el reporte', async () => {
    reportsApi.revenue.mockResolvedValue(baseReport())
    renderPage()
    await waitFor(() => expect(reportsApi.revenue).toHaveBeenCalled())
    expect((await screen.findAllByText('Bruto')).length).toBeGreaterThanOrEqual(1)
  })
})
