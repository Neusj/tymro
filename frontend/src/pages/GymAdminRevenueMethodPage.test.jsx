import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  reportsApi: { revenuePayments: vi.fn(), exportRevenuePayments: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, reportsApi } from '../api/client'
import GymAdminRevenueMethodPage from './GymAdminRevenueMethodPage'

// La página lee `method` con useParams(), y eso solo se llena si el componente cuelga de
// un <Route> que declara ":method" — montarla suelta dentro de un MemoryRouter (sin
// Routes/Route) deja useParams() en {} y rompe tanto la llamada a la API (sin `method`)
// como el criterio "es un método manual" que decide si se esconde el bloque de devoluciones.
const renderPage = (initialEntry) =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/gym-admin/reports/revenue/:method" element={<GymAdminRevenueMethodPage />} />
      </Routes>
    </MemoryRouter>,
  )

const baseReport = (over = {}) => ({
  period: { date_from: '2026-07-01', date_to: '2026-07-31', days: 31, granularity: 'day' },
  filters: { branch_id: null, branch_name: null, method: 'mercadopago', method_label: 'MercadoPago' },
  totals: { gross: 840000, refunds: 35000, net: 805000, payments_count: 12, refunds_count: 1 },
  rows: [
    {
      kind: 'mercadopago',
      id: '3f2b1111-0000-0000-0000-000000000001',
      occurred_at: '2026-07-03T14:02:11-04:00',
      amount: 70000,
      student_id: 5,
      student_name: 'Ana Pérez',
      plan_name: 'Mensual 12',
      branch_id: 2,
      branch_name: 'Sede Centro',
      method: 'mercadopago',
      method_label: 'MercadoPago',
    },
  ],
  refund_rows: [
    {
      kind: 'mercadopago',
      id: '9a1c2222-0000-0000-0000-000000000002',
      occurred_at: '2026-07-18T10:00:00-04:00',
      amount: 35000,
      student_id: 7,
      student_name: 'Sara Díaz',
      plan_name: 'Mensual 8',
      branch_id: 2,
      branch_name: 'Sede Centro',
      method: 'mercadopago',
      method_label: 'MercadoPago',
      collected_at: '2026-06-22T09:12:00-04:00',
      collected_in_period: false,
    },
  ],
  row_limit: 2000,
  truncated: false,
  refunds_truncated: false,
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  branchesApi.list.mockResolvedValue([])
})

describe('GymAdminRevenueMethodPage', () => {
  it('renderiza rows (cobros) y refund_rows (devoluciones) en secciones separadas, cada fila navegable a la capa 3', async () => {
    reportsApi.revenuePayments.mockResolvedValue(baseReport())
    renderPage('/gym-admin/reports/revenue/mercadopago?date_from=2026-07-01&date_to=2026-07-31')

    const cobroLink = await screen.findByRole('link', { name: /Ana Pérez/ })
    expect(cobroLink).toHaveAttribute(
      'href',
      '/gym-admin/reports/revenue/mercadopago/3f2b1111-0000-0000-0000-000000000001?date_from=2026-07-01&date_to=2026-07-31',
    )

    const refundLink = await screen.findByRole('link', { name: /Sara Díaz/ })
    expect(refundLink).toHaveAttribute(
      'href',
      '/gym-admin/reports/revenue/mercadopago/9a1c2222-0000-0000-0000-000000000002?date_from=2026-07-01&date_to=2026-07-31',
    )

    // La devolución con collected_in_period:false rotula que el cobro original quedó
    // fuera del período — sin este rótulo el número de arriba parece descuadrado.
    expect(screen.getByText(/fuera del período/)).toBeInTheDocument()
  })

  it('con método manual (cash/transfer/unknown) y refund_rows=[] muestra el texto explícito de que no hay devolución', async () => {
    reportsApi.revenuePayments.mockResolvedValue(
      baseReport({
        filters: { branch_id: null, branch_name: null, method: 'cash', method_label: 'Efectivo' },
        rows: [],
        refund_rows: [],
      }),
    )
    renderPage('/gym-admin/reports/revenue/cash?date_from=2026-07-01&date_to=2026-07-31')

    expect(
      await screen.findByText(/no tienen devolución en el sistema/),
    ).toBeInTheDocument()
    // La sección NO se esconde: sigue con su título "Devoluciones" arriba del texto
    // ("Devoluciones" también es el title de la StatCard de la ecuación, por eso se pide
    // el <h2> puntual y no cualquier texto que matchee).
    expect(screen.getByRole('heading', { name: 'Devoluciones', level: 2 })).toBeInTheDocument()
  })

  it('con truncated=true avisa que la lista de cobros está recortada', async () => {
    reportsApi.revenuePayments.mockResolvedValue(baseReport({ truncated: true, row_limit: 1 }))
    renderPage('/gym-admin/reports/revenue/mercadopago?date_from=2026-07-01&date_to=2026-07-31')

    expect(await screen.findByText(/primeros 1 cobros/)).toBeInTheDocument()
  })

  it('con refunds_truncated=true avisa que la lista de devoluciones está recortada', async () => {
    reportsApi.revenuePayments.mockResolvedValue(baseReport({ refunds_truncated: true }))
    renderPage('/gym-admin/reports/revenue/mercadopago?date_from=2026-07-01&date_to=2026-07-31')

    expect(await screen.findByText(/primeras.*devoluciones/)).toBeInTheDocument()
  })

  it('propaga method a la llamada de la API y NO lo repite en la query string de los links', async () => {
    reportsApi.revenuePayments.mockResolvedValue(baseReport())
    renderPage('/gym-admin/reports/revenue/mercadopago?date_from=2026-07-01&date_to=2026-07-31&branch_id=2')

    await waitFor(() => expect(reportsApi.revenuePayments).toHaveBeenCalled())
    const [params] = reportsApi.revenuePayments.mock.calls[0]
    expect(params).toMatchObject({ method: 'mercadopago', date_from: '2026-07-01', date_to: '2026-07-31', branch_id: '2' })
  })
})
