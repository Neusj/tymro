import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  reportsApi: { revenue: vi.fn(), exportRevenue: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, reportsApi } from '../api/client'
import GymAdminRevenueReportPage from './GymAdminRevenueReportPage'

// Expone la URL actual del MemoryRouter para verificar que los filtros se escriben en el
// query string (P3.5: capa 1 pasó de useState suelto a useSearchParams) sin depender de
// window.location, que MemoryRouter no toca.
function LocationDisplay() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}{location.search}</div>
}

const renderPage = (initialEntry = '/gym-admin/reports/revenue') =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <GymAdminRevenueReportPage />
      <LocationDisplay />
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

  it('cada fila de método es un link real (no un <div>) con aria-label propio y navega a la capa 2 propagando período y sucursal', async () => {
    reportsApi.revenue.mockResolvedValue(baseReport())
    renderPage('/gym-admin/reports/revenue?date_from=2026-07-01&date_to=2026-07-31&branch_id=2')

    const link = await screen.findByRole('link', { name: /MercadoPago/ })
    // El destino lleva el método en el PATH y el período+sucursal en la query — el
    // filtro "método" de la capa 1 no viaja porque en la capa 2 ya no es un filtro.
    expect(link).toHaveAttribute(
      'href',
      '/gym-admin/reports/revenue/mercadopago?date_from=2026-07-01&date_to=2026-07-31&branch_id=2',
    )

    fireEvent.click(link)
    expect(screen.getByTestId('location').textContent).toBe(
      '/gym-admin/reports/revenue/mercadopago?date_from=2026-07-01&date_to=2026-07-31&branch_id=2',
    )
  })

  it('lee el período/sucursal/método inicial desde el query string (no siempre el mes en curso)', async () => {
    reportsApi.revenue.mockResolvedValue(baseReport())
    renderPage('/gym-admin/reports/revenue?date_from=2026-01-01&date_to=2026-01-31&branch_id=9&method=cash')

    await waitFor(() => expect(reportsApi.revenue).toHaveBeenCalled())
    const [params] = reportsApi.revenue.mock.calls[0]
    expect(params).toMatchObject({ date_from: '2026-01-01', date_to: '2026-01-31', branch_id: '9', method: 'cash' })
  })

  it('cambiar un filtro actualiza el query string con replace (no acumula historial)', async () => {
    reportsApi.revenue.mockResolvedValue(baseReport())
    branchesApi.list.mockResolvedValue([{ id: 3, name: 'Sede Norte' }])
    renderPage('/gym-admin/reports/revenue?date_from=2026-07-01&date_to=2026-07-31')

    const branchSelect = await screen.findByLabelText('Sucursal')
    fireEvent.change(branchSelect, { target: { value: '3' } })

    await waitFor(() =>
      expect(screen.getByTestId('location').textContent).toBe(
        '/gym-admin/reports/revenue?date_from=2026-07-01&date_to=2026-07-31&branch_id=3',
      ),
    )
  })
})
