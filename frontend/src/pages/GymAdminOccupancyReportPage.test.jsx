import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  disciplinesApi: { list: vi.fn() },
  reportsApi: { occupancy: vi.fn(), exportOccupancy: vi.fn() },
  downloadReportFile: vi.fn(),
}))

import { branchesApi, disciplinesApi, reportsApi } from '../api/client'
import GymAdminOccupancyReportPage from './GymAdminOccupancyReportPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/reports/occupancy']}>
      <GymAdminOccupancyReportPage />
    </MemoryRouter>,
  )

const baseReport = (over = {}) => ({
  period: { date_from: '2026-08-01', date_to: '2026-08-06', days: 6, granularity: 'day' },
  filters: { branch_id: null, branch_name: null, discipline_id: null, discipline_name: null },
  totals: {
    classes: 40,
    capacity: 400,
    enrolled: 280,
    occupancy_rate: 70,
    full_classes: 12,
    empty_classes: 4,
    pruned_classes: 0,
  },
  by_discipline: [],
  by_hour: [],
  series: [
    { bucket: '2026-08-01', classes: 6, capacity: 60, enrolled: 40, occupancy_rate: 66.7 },
    { bucket: '2026-08-02', classes: 7, capacity: 70, enrolled: 50, occupancy_rate: 71.4 },
  ],
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  branchesApi.list.mockResolvedValue([])
  disciplinesApi.list.mockResolvedValue([])
})

describe('GymAdminOccupancyReportPage', () => {
  it('muestra el % de ocupación del período y clases llenas vs. vacías', async () => {
    reportsApi.occupancy.mockResolvedValue(baseReport())
    renderPage()

    expect(await screen.findByText('70%')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument() // llenas
    expect(screen.getByText('4')).toBeInTheDocument() // vacías
    expect(screen.getByText('Clases llenas')).toBeInTheDocument()
    expect(screen.getByText('Clases vacías')).toBeInTheDocument()

    // Sin clases podadas: no debe aparecer la nota de "dato de marketing".
    expect(screen.queryByText(/dato de marketing/)).not.toBeInTheDocument()
  })

  it('con pruned_classes > 0 indica que incluye clases vacías ya archivadas (dato de marketing)', async () => {
    reportsApi.occupancy.mockResolvedValue(baseReport({ totals: { ...baseReport().totals, pruned_classes: 4 } }))
    renderPage()

    expect(await screen.findByText(/Incluye 4 clases vacías ya archivadas/)).toBeInTheDocument()
    expect(screen.getByText(/dato de marketing/)).toBeInTheDocument()
  })

  it('con series de un solo punto y un desglose vacío no revienta', async () => {
    reportsApi.occupancy.mockResolvedValue(
      baseReport({ series: [{ bucket: '2026-08-01', classes: 1, capacity: 10, enrolled: 5, occupancy_rate: 50 }] }),
    )
    renderPage()

    await waitFor(() => expect(reportsApi.occupancy).toHaveBeenCalled())
    expect(screen.getAllByText('Sin clases en el período.').length).toBe(2) // por disciplina + por horario
  })
})
