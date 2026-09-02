import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  reportsApi: { trialConversion: vi.fn(), exportTrialConversion: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, reportsApi } from '../api/client'
import GymAdminTrialConversionReportPage from './GymAdminTrialConversionReportPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/reports/trial-conversion']}>
      <GymAdminTrialConversionReportPage />
    </MemoryRouter>,
  )

const baseReport = (over = {}) => ({
  period: { date_from: '2026-08-01', date_to: '2026-08-06', days: 6, granularity: 'day' },
  filters: { branch_id: null, branch_name: null, conversion_window_days: 60 },
  totals: {
    trials: 40,
    converted: 18,
    conversion_rate: 45.0,
    attended: 30,
    converted_attended: 16,
    attended_conversion_rate: 53.3,
    refunded_conversions: 0,
    pending_window: 0,
    cancelled_trials: 2,
    pending_trials: 3,
  },
  previous: { period: {}, totals: {} },
  comparison: {
    conversion_rate_delta_pp: 3.2,
    trials_delta: 5,
    trials_delta_pct: 14.3,
    converted_delta: 2,
    converted_delta_pct: 12.5,
  },
  unbacked_trial_flags: { students: 0, scope: 'organization', excluded_from_rate: true },
  series: [
    { bucket: '2026-08-01', trials: 6, converted: 2 },
    { bucket: '2026-08-02', trials: 7, converted: 3 },
  ],
  prospects: [
    {
      id: 11,
      student_id: 11,
      name: 'Ana Perez',
      email: 'ana@test.local',
      phone: '+56 9 1111 2222',
      trial_date: '2026-08-01',
      conversion_deadline: '2026-09-30',
      attended: true,
      converted: true,
      conversion_status: 'converted',
      conversion_status_label: 'Compró',
      trial_classes: [
        {
          id: 21,
          name: 'Boxeo',
          branch_name: 'Centro',
          teacher_name: 'Ignacio Duarte',
          discipline_name: 'Boxeo',
          class_type_name: 'Grupal',
          start_datetime: '2026-08-01T13:30:00Z',
          start_time: '09:30',
        },
      ],
      membership: {
        id: 31,
        plan_id: 41,
        plan_name: 'Pack 8',
        start_date: '2026-08-02',
        end_date: '2026-09-01',
        final_price: 30000,
      },
    },
    {
      id: 12,
      student_id: 12,
      name: 'Bruno Rojas',
      email: 'bruno@test.local',
      phone: '',
      trial_date: '2026-08-02',
      conversion_deadline: '2026-10-01',
      attended: false,
      converted: false,
      conversion_status: 'pending',
      conversion_status_label: 'Pendiente',
      trial_classes: [],
      membership: null,
    },
  ],
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
  branchesApi.list.mockResolvedValue([{ id: 1, name: 'Centro' }])
})

describe('GymAdminTrialConversionReportPage', () => {
  it('muestra la tasa de conversión y el bruto (probaron/compraron) bien visibles', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    expect(await screen.findByText('45.0%')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument() // probaron
    expect(screen.getByText('18')).toBeInTheDocument() // compraron
    expect(screen.getByText('Tasa de conversión')).toBeInTheDocument()
    // "Probaron"/"Compraron" aparecen en la StatCard Y en la leyenda del gráfico de
    // evolución (mismo patrón que el test de Revenue con "Bruto"/"Devoluciones"/"Neto").
    expect(screen.getAllByText('Probaron').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Compraron').length).toBeGreaterThanOrEqual(1)
  })

  it('abre desde Probaron una lista con tabs y detalle de prospectos', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await screen.findByText('45.0%')
    await userEvent.click(screen.getByRole('button', { name: /ver todos los prospectos que probaron/i }))

    const detail = await screen.findByRole('region', { name: /detalle de prospectos/i })
    expect(within(detail).getByRole('button', { name: 'Todos' })).toHaveAttribute('aria-current', 'true')
    expect(within(detail).getAllByText('Ana Perez').length).toBeGreaterThanOrEqual(1)
    expect(within(detail).getAllByText('Bruno Rojas').length).toBeGreaterThanOrEqual(1)
    expect(within(detail).getByText('ana@test.local')).toBeInTheDocument()
    expect(within(detail).getByText('+56 9 1111 2222')).toBeInTheDocument()
    expect(within(detail).getAllByText('Boxeo').length).toBeGreaterThanOrEqual(1)
    expect(within(detail).getAllByText('Pack 8').length).toBeGreaterThanOrEqual(1)
  })

  it('abre desde Compraron filtrando solo los prospectos convertidos', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await screen.findByText('45.0%')
    await userEvent.click(screen.getByRole('button', { name: /ver prospectos que compraron/i }))

    const detail = await screen.findByRole('region', { name: /detalle de prospectos/i })
    expect(within(detail).getByRole('button', { name: 'Compraron' })).toHaveAttribute('aria-current', 'true')
    expect(within(detail).getAllByText('Ana Perez').length).toBeGreaterThanOrEqual(1)
    expect(within(detail).queryAllByText('Bruno Rojas')).toHaveLength(0)

    await userEvent.click(within(detail).getByRole('button', { name: 'Todos' }))
    expect(within(detail).getAllByText('Bruno Rojas').length).toBeGreaterThanOrEqual(1)
  })

  it('con conversion_rate null muestra guion, NUNCA 0% ni 100%', async () => {
    reportsApi.trialConversion.mockResolvedValue(
      baseReport({
        totals: { ...baseReport().totals, conversion_rate: null, attended_conversion_rate: null },
        comparison: { ...baseReport().comparison, conversion_rate_delta_pp: null },
      }),
    )
    renderPage()

    await waitFor(() => expect(reportsApi.trialConversion).toHaveBeenCalled())
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
    expect(screen.queryByText('100.0%')).not.toBeInTheDocument()
  })

  it('muestra la tasa "solo asistieron" como dato complementario, aclarado y separado de la principal', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    expect(await screen.findByText('53.3%')).toBeInTheDocument()
    expect(screen.getByText(/Dato complementario: solo alumnos que asistieron/)).toBeInTheDocument()
    expect(screen.getByText(/marca a todos como ausentes/)).toBeInTheDocument()
  })

  it('con pending_window > 0 avisa que el veredicto está abierto y la tasa puede subir', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport({ totals: { ...baseReport().totals, pending_window: 6 } }))
    renderPage()

    expect(await screen.findByText(/6 alumnos probaron hace poco/)).toBeInTheDocument()
    expect(screen.getByText(/la tasa de conversión\s*puede subir/)).toBeInTheDocument()
  })

  it('sin pending_window no muestra el aviso de veredicto abierto', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.trialConversion).toHaveBeenCalled())
    expect(screen.queryByText(/veredicto está abierto/)).not.toBeInTheDocument()
  })

  it('con refunded_conversions > 0 avisa que esas compras ya no cuentan como conversión', async () => {
    reportsApi.trialConversion.mockResolvedValue(
      baseReport({ totals: { ...baseReport().totals, refunded_conversions: 4 } }),
    )
    renderPage()

    expect(await screen.findByText(/4 compras posteriores a la clase de prueba se devolvieron/)).toBeInTheDocument()
  })

  it('sin refunded_conversions no muestra el aviso de devoluciones', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.trialConversion).toHaveBeenCalled())
    expect(screen.queryByText(/se devolvieron/)).not.toBeInTheDocument()
  })

  it('muestra cancelled_trials y pending_trials como nota al pie, fuera de la tasa', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    expect(await screen.findByText(/2 clases de prueba canceladas y 3 todavía no se dictan/)).toBeInTheDocument()
    expect(screen.getByText(/quedan fuera de la tasa de conversión/)).toBeInTheDocument()
  })

  it('con unbacked_trial_flags.students > 0 muestra la nota discreta a nivel organización', async () => {
    reportsApi.trialConversion.mockResolvedValue(
      baseReport({ unbacked_trial_flags: { students: 7, scope: 'organization', excluded_from_rate: true } }),
    )
    renderPage()

    expect(await screen.findByText(/7 alumnos \(a nivel organización, no solo esta sucursal\/período\)/)).toBeInTheDocument()
  })

  it('con unbacked_trial_flags.students en 0 no muestra la nota de alumnos sin respaldo', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.trialConversion).toHaveBeenCalled())
    expect(screen.queryByText(/sin una reserva de prueba registrada/)).not.toBeInTheDocument()
  })

  it('cambiar la sucursal dispara un refetch con branch_id', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.trialConversion).toHaveBeenCalledTimes(1))

    const branchSelect = screen.getByLabelText(/sucursal/i)
    await userEvent.selectOptions(branchSelect, '1')

    await waitFor(() =>
      expect(reportsApi.trialConversion).toHaveBeenLastCalledWith(expect.objectContaining({ branch_id: '1' })),
    )
  })

  it('cambiar la fecha "desde" dispara un refetch con la nueva fecha', async () => {
    reportsApi.trialConversion.mockResolvedValue(baseReport())
    renderPage()

    await waitFor(() => expect(reportsApi.trialConversion).toHaveBeenCalledTimes(1))

    const dateFromInput = screen.getByLabelText(/desde/i)
    await userEvent.clear(dateFromInput)
    await userEvent.type(dateFromInput, '2026-07-01')

    await waitFor(() =>
      expect(reportsApi.trialConversion).toHaveBeenLastCalledWith(expect.objectContaining({ date_from: '2026-07-01' })),
    )
  })
})
