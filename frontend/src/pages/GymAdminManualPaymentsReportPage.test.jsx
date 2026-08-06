import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  reportsApi: { manualPayments: vi.fn(), exportManualPayments: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, reportsApi } from '../api/client'
import GymAdminManualPaymentsReportPage from './GymAdminManualPaymentsReportPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/reports/manual-payments']}>
      <GymAdminManualPaymentsReportPage />
    </MemoryRouter>,
  )

const baseReport = (over = {}) => ({
  period: { date_from: '2026-08-01', date_to: '2026-08-06', days: 6, granularity: 'day' },
  filters: { branch_id: null, branch_name: null, method: null, method_label: null },
  totals: { cash: 500000, transfer: 300000, unknown: 0, total: 800000, count: 9, cash_count: 6, transfer_count: 3, unknown_count: 0 },
  rows: [
    {
      id: 1,
      recorded_at: '2026-08-05T15:30:00Z',
      amount: '100000.00',
      method: 'cash',
      method_label: 'Efectivo',
      reference: null,
      student_id: 1,
      student_name: 'Ana Pérez',
      student_plan_id: 5,
      plan_name: 'Mensual',
      branch_id: 1,
      branch_name: 'Centro',
      recorded_by_id: 9,
      recorded_by_name: 'Recepción Centro',
    },
    {
      id: 2,
      recorded_at: '2026-08-04T10:00:00Z',
      amount: '50000.00',
      method: 'transfer',
      method_label: 'Transferencia',
      reference: 'TRX-123',
      student_id: 2,
      student_name: 'Bruno Díaz',
      student_plan_id: 6,
      plan_name: 'Trimestral',
      branch_id: 1,
      branch_name: 'Centro',
      recorded_by_name: 'Coty Gómez',
    },
  ],
  row_limit: 500,
  truncated: false,
  series: [
    { bucket: '2026-08-01', cash: 100000, transfer: 50000, unknown: 0, total: 150000 },
    { bucket: '2026-08-02', cash: 200000, transfer: 100000, unknown: 0, total: 300000 },
  ],
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  branchesApi.list.mockResolvedValue([])
})

describe('GymAdminManualPaymentsReportPage', () => {
  it('la tabla de detalle muestra el método y quién registró cada cobro', async () => {
    reportsApi.manualPayments.mockResolvedValue(baseReport())
    renderPage()

    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    // Fila de encabezado + 2 filas de datos.
    expect(rows).toHaveLength(3)

    expect(within(table).getByText('Ana Pérez')).toBeInTheDocument()
    expect(within(table).getByText('Efectivo')).toBeInTheDocument()
    expect(within(table).getByText('Recepción Centro')).toBeInTheDocument()

    expect(within(table).getByText('Bruno Díaz')).toBeInTheDocument()
    expect(within(table).getByText('Transferencia')).toBeInTheDocument()
    expect(within(table).getByText('Coty Gómez')).toBeInTheDocument()
  })

  it('el KPI separa el total en efectivo del total en transferencia (+ cantidad de cobros)', async () => {
    reportsApi.manualPayments.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(screen.getAllByText('$500.000').length).toBeGreaterThanOrEqual(1)) // efectivo
    expect(screen.getAllByText('$300.000').length).toBeGreaterThanOrEqual(1) // transferencia
    expect(screen.getAllByText('$800.000').length).toBeGreaterThanOrEqual(1) // total

    // Cantidad de cobros por medio, visible como hint de cada tarjeta.
    expect(screen.getByText('6 cobros')).toBeInTheDocument()
    expect(screen.getByText('3 cobros')).toBeInTheDocument()
    expect(screen.getByText('9 cobros en total')).toBeInTheDocument()

    // Sin cobros históricos sin método (unknown=0): la 4ª tarjeta NO debe aparecer.
    expect(screen.queryByText('Sin método registrado', { selector: 'p' })).not.toBeInTheDocument()
  })

  it('con truncated=true muestra el aviso de que la lista está recortada (los totales no)', async () => {
    reportsApi.manualPayments.mockResolvedValue(baseReport({ truncated: true, row_limit: 2 }))
    renderPage()

    expect(await screen.findByText(/primeros 2 registros/)).toBeInTheDocument()
    expect(screen.getByText(/totales y gráficos de\s*arriba SÍ son del período completo/)).toBeInTheDocument()
  })

  it('con totals.unknown > 0 muestra el subtotal "Sin método registrado" (cobros históricos sin instrumento)', async () => {
    reportsApi.manualPayments.mockResolvedValue(
      baseReport({
        totals: {
          cash: 500000,
          transfer: 300000,
          unknown: 40000,
          total: 840000,
          count: 10,
          cash_count: 6,
          transfer_count: 3,
          unknown_count: 1,
        },
      }),
    )
    renderPage()

    // "$40.000" aparece en la StatCard nueva Y en la fila del gráfico de desglose.
    await waitFor(() => expect(screen.getAllByText('$40.000').length).toBeGreaterThanOrEqual(1))
    expect(screen.getAllByText(/cobros históricos sin instrumento declarado/).length).toBeGreaterThanOrEqual(1)
  })
})
