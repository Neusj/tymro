import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  getPlans: vi.fn(),
  reportsApi: { retention: vi.fn(), exportRetention: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, getPlans, reportsApi } from '../api/client'
import GymAdminRetentionReportPage from './GymAdminRetentionReportPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/reports/retention']}>
      <GymAdminRetentionReportPage />
    </MemoryRouter>,
  )

const baseReport = (over = {}) => ({
  period: { date_from: '2026-08-01', date_to: '2026-08-06', days: 6, granularity: 'day' },
  filters: {
    branch_id: null,
    branch_name: null,
    plan_id: null,
    plan_name: null,
    renewal_grace_days: 30,
    upcoming_window_days: 30,
    includes_global_plans: true,
  },
  totals: {
    expired: 20,
    renewed: 12,
    lost: 8,
    switched_plan: 3,
    churned: 5,
    pending_grace: 0,
    global_plan_memberships: 0,
    renewal_rate: 60.0,
    retention_rate: 75.0,
  },
  previous: { period: {}, totals: {} },
  comparison: {
    renewal_rate_delta_pp: 4.5,
    retention_rate_delta_pp: -2.1,
    expired_delta: 2,
    expired_delta_pct: 11.1,
    renewed_delta: 1,
    renewed_delta_pct: 9.1,
  },
  upcoming: {
    as_of: '2026-08-06',
    window_days: 30,
    date_from: '2026-08-06',
    date_to: '2026-09-05',
    expiring: 5,
    already_renewed: 2,
    at_risk: 3,
    overlaps_period: false,
  },
  by_plan: [
    { plan_id: 1, plan_name: 'Mensual', expired: 15, renewed: 10, lost: 5, switched_plan: 2, churned: 3, renewal_rate: 66.7, retention_rate: 80.0 },
    { plan_id: null, plan_name: 'Sin plan', expired: 5, renewed: 2, lost: 3, switched_plan: 1, churned: 2, renewal_rate: null, retention_rate: null },
  ],
  series: [
    { bucket: '2026-08-01', expired: 3, renewed: 2 },
    { bucket: '2026-08-02', expired: 4, renewed: 3 },
  ],
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  branchesApi.list.mockResolvedValue([{ id: 1, name: 'Centro' }])
  getPlans.mockResolvedValue([{ id: 1, name: 'Mensual', is_active: true }])
})

describe('GymAdminRetentionReportPage', () => {
  it('muestra vencieron/renovaron/perdidos y las DOS tasas por separado, sin mezclarlas', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    expect((await screen.findAllByText('20')).length).toBeGreaterThanOrEqual(1) // vencieron
    expect(screen.getAllByText('12').length).toBeGreaterThanOrEqual(1) // renovaron
    expect(screen.getAllByText('8').length).toBeGreaterThanOrEqual(1) // perdidos

    // Las dos tasas, ambas visibles y con etiqueta propia (no una sola tasa genérica).
    expect(screen.getByText('60.0%')).toBeInTheDocument() // renewal_rate
    expect(screen.getByText('75.0%')).toBeInTheDocument() // retention_rate
    expect(screen.getByText('Tasa de renovación')).toBeInTheDocument()
    expect(screen.getByText('Tasa de retención')).toBeInTheDocument()
  })

  it('con renewal_rate y retention_rate null muestra guion, NUNCA 0% ni 100%', async () => {
    reportsApi.retention.mockResolvedValue(
      baseReport({
        totals: { ...baseReport().totals, renewal_rate: null, retention_rate: null },
        comparison: { ...baseReport().comparison, renewal_rate_delta_pp: null, retention_rate_delta_pp: null },
      }),
    )
    renderPage()

    await waitFor(() => expect(reportsApi.retention).toHaveBeenCalled())
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
    expect(screen.queryByText('100.0%')).not.toBeInTheDocument()
  })

  it('con pending_grace > 0 avisa que la tasa es provisoria', async () => {
    reportsApi.retention.mockResolvedValue(baseReport({ totals: { ...baseReport().totals, pending_grace: 4 } }))
    renderPage()

    expect(await screen.findByText(/4 vencimientos todavía están dentro de la ventana de gracia/)).toBeInTheDocument()
    expect(screen.getByText(/provisorias, no definitivas/)).toBeInTheDocument()
  })

  it('sin pending_grace no muestra el aviso de tasa provisoria', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.retention).toHaveBeenCalled())
    expect(screen.queryByText(/ventana de gracia/)).not.toBeInTheDocument()
  })

  it('con sucursal seleccionada avisa que incluye membresías globales y que no suma al total de la organización', async () => {
    reportsApi.retention.mockResolvedValue(
      baseReport({
        filters: { ...baseReport().filters, branch_id: 1, branch_name: 'Centro' },
        totals: { ...baseReport().totals, global_plan_memberships: 3 },
      }),
    )
    renderPage()

    expect(await screen.findByText(/incluye a propósito 3 membresías de planes globales/)).toBeInTheDocument()
    expect(screen.getByText(/NO suman el total de la organización/)).toBeInTheDocument()
  })

  it('sin sucursal seleccionada no muestra el aviso de membresías globales', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.retention).toHaveBeenCalled())
    expect(screen.queryByText(/membresías de planes globales/)).not.toBeInTheDocument()
  })

  it('el bloque "por vencer" se rotula como anclado en HOY, no en el período consultado', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    const heading = await screen.findByText(/Por vencer — próximos 30 días desde HOY/)
    const upcomingSection = heading.closest('section')
    expect(within(upcomingSection).getByText(/Anclado en hoy \(2026-08-06\)/)).toBeInTheDocument()
    expect(within(upcomingSection).getByText('5')).toBeInTheDocument() // expiring
  })

  it('la tabla "por plan" muestra un plan_id null como fila propia ("Sin plan")', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    const table = await screen.findByRole('table')
    expect(within(table).getByText('Mensual')).toBeInTheDocument()
    expect(within(table).getByText('Sin plan')).toBeInTheDocument()
    // Fila con tasas null → guion en la tabla también.
    const rows = within(table).getAllByRole('row')
    expect(rows.length).toBe(3) // encabezado + 2 planes
  })

  it('cambiar la sucursal dispara un refetch con branch_id', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.retention).toHaveBeenCalledTimes(1))

    const branchSelect = screen.getByLabelText(/sucursal/i)
    await userEvent.selectOptions(branchSelect, '1')

    await waitFor(() =>
      expect(reportsApi.retention).toHaveBeenLastCalledWith(expect.objectContaining({ branch_id: '1' })),
    )
  })

  it('cambiar el plan dispara un refetch con plan_id', async () => {
    reportsApi.retention.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.retention).toHaveBeenCalledTimes(1))

    const planSelect = screen.getByLabelText(/^plan/i)
    await userEvent.selectOptions(planSelect, '1')

    await waitFor(() =>
      expect(reportsApi.retention).toHaveBeenLastCalledWith(expect.objectContaining({ plan_id: '1' })),
    )
  })
})
