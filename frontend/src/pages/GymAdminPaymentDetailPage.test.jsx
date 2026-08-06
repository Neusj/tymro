import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  reportsApi: { revenuePaymentDetail: vi.fn() },
}))

import { reportsApi } from '../api/client'
import GymAdminPaymentDetailPage from './GymAdminPaymentDetailPage'

// Igual que en GymAdminRevenueMethodPage.test.jsx: `kind`/`id` vienen de useParams() y
// solo se llenan si el componente cuelga de un <Route> que declara ":kind/:id".
const renderPage = (initialEntry) =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/gym-admin/reports/revenue/:kind/:id" element={<GymAdminPaymentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

const manualDetail = (over = {}) => ({
  kind: 'manual',
  id: 123,
  amount: 20000,
  recorded_at: '2026-07-05T12:00:00-04:00',
  method: 'cash',
  method_label: 'Efectivo',
  reference: 'caja 2',
  student_id: 5,
  student_name: 'Ana Pérez',
  student_plan_id: 88,
  plan_name: 'Mensual 12',
  branch_id: 2,
  branch_name: 'Sede Centro',
  recorded_by_id: 3,
  recorded_by_name: 'Javier Neus',
  ...over,
})

const mercadopagoDetail = (over = {}) => ({
  kind: 'mercadopago',
  id: '3f2b1111-0000-0000-0000-000000000001',
  amount: 70000,
  currency: 'CLP',
  method: 'mercadopago',
  method_label: 'MercadoPago',
  collected_at: '2026-07-03T14:02:11-04:00',
  status: 'approved',
  status_detail: 'accredited',
  provider: 'mercadopago',
  provider_payment_id: '12345',
  processed_at: '2026-07-03T14:02:15-04:00',
  refunded_at: null,
  refunded_amount: 0,
  plan_amount: 70000,
  enrollment_fee_amount: 0,
  student_id: 5,
  student_name: 'Ana Pérez',
  student_plan_id: 88,
  plan_name: 'Mensual 12',
  branch_id: 2,
  branch_name: 'Sede Centro',
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('GymAdminPaymentDetailPage', () => {
  it('pago manual: muestra "Registrado por" y NO muestra "ID de transacción" ni "Estado"', async () => {
    reportsApi.revenuePaymentDetail.mockResolvedValue(manualDetail())
    renderPage('/gym-admin/reports/revenue/manual/123')

    expect(await screen.findByText('Registrado por')).toBeInTheDocument()
    expect(screen.getByText('Javier Neus')).toBeInTheDocument()
    expect(screen.queryByText('ID de transacción')).not.toBeInTheDocument()
    expect(screen.queryByText('Estado')).not.toBeInTheDocument()

    expect(reportsApi.revenuePaymentDetail).toHaveBeenCalledWith('manual', '123')
  })

  it('pago MercadoPago: muestra "ID de transacción" y la fecha de cobro, y NO muestra "Registrado por"', async () => {
    reportsApi.revenuePaymentDetail.mockResolvedValue(mercadopagoDetail())
    renderPage('/gym-admin/reports/revenue/mercadopago/3f2b1111-0000-0000-0000-000000000001')

    expect(await screen.findByText('ID de transacción')).toBeInTheDocument()
    expect(screen.getByText('12345')).toBeInTheDocument()
    expect(screen.getByText('Fecha de cobro')).toBeInTheDocument()
    expect(screen.queryByText('Registrado por')).not.toBeInTheDocument()
  })

  it('campos null/vacíos no se renderizan: ni la etiqueta ni un guion o "N/A"', async () => {
    reportsApi.revenuePaymentDetail.mockResolvedValue(
      manualDetail({ reference: '', branch_name: null }),
    )
    renderPage('/gym-admin/reports/revenue/manual/123')

    await screen.findByText('Registrado por')
    expect(screen.queryByText('Referencia')).not.toBeInTheDocument()
    expect(screen.queryByText('Sede')).not.toBeInTheDocument()
    expect(screen.queryByText('—')).not.toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })

  it('refunded_amount=0 y enrollment_fee_amount=0 no se muestran (solo aparecen si son > 0)', async () => {
    reportsApi.revenuePaymentDetail.mockResolvedValue(mercadopagoDetail())
    renderPage('/gym-admin/reports/revenue/mercadopago/3f2b1111-0000-0000-0000-000000000001')

    await screen.findByText('ID de transacción')
    expect(screen.queryByText('Monto devuelto')).not.toBeInTheDocument()
    expect(screen.queryByText('Matrícula')).not.toBeInTheDocument()
  })

  it('con refunded_amount > 0 sí muestra "Monto devuelto"', async () => {
    reportsApi.revenuePaymentDetail.mockResolvedValue(
      mercadopagoDetail({ refunded_at: '2026-07-20T10:00:00-04:00', refunded_amount: 35000 }),
    )
    renderPage('/gym-admin/reports/revenue/mercadopago/3f2b1111-0000-0000-0000-000000000001')

    expect(await screen.findByText('Monto devuelto')).toBeInTheDocument()
    expect(screen.getByText('$35.000')).toBeInTheDocument()
  })

  it('un 404 muestra un mensaje sobrio y no revela más información', async () => {
    reportsApi.revenuePaymentDetail.mockRejectedValue({ response: { status: 404, data: { detail: 'super detalle interno' } } })
    renderPage('/gym-admin/reports/revenue/manual/999')

    expect(await screen.findByText('No se encontró ese pago.')).toBeInTheDocument()
    expect(screen.queryByText('super detalle interno')).not.toBeInTheDocument()
  })

  it('el back conserva date_from/date_to/branch_id y apunta a la capa 2 del método real del pago', async () => {
    reportsApi.revenuePaymentDetail.mockResolvedValue(manualDetail({ method: 'cash' }))
    renderPage('/gym-admin/reports/revenue/manual/123?date_from=2026-07-01&date_to=2026-07-31&branch_id=2')

    await waitFor(() => expect(reportsApi.revenuePaymentDetail).toHaveBeenCalled())
    const backLink = await screen.findByRole('link', { name: /Volver/ })
    expect(backLink).toHaveAttribute(
      'href',
      '/gym-admin/reports/revenue/cash?date_from=2026-07-01&date_to=2026-07-31&branch_id=2',
    )
  })
})
