import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import StudentPersonalizedClassesPage from './StudentPersonalizedClassesPage'
import { personalizedClassesApi } from '../api/client'

vi.mock('../api/client', () => ({
  personalizedClassesApi: {
    list: vi.fn(),
  },
}))

describe('StudentPersonalizedClassesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('muestra clases personalizadas en curso, dictadas y anuladas del alumno', async () => {
    personalizedClassesApi.list.mockResolvedValue({
      count: 3,
      page: 1,
      page_size: 10,
      total_pages: 1,
      results: [
        {
          id: 1,
          status: 'confirmed',
          teacher: 'Profe Ana',
          confirmed_at: '2026-08-24T14:00:00Z',
          student_plan_name: 'Privadas 10',
        },
        {
          id: 2,
          status: 'finished',
          teacher: 'Profe Bea',
          confirmed_at: '2026-08-23T14:00:00Z',
          finished_at: '2026-08-23T15:00:00Z',
          student_plan_name: 'Privadas 10',
        },
        {
          id: 3,
          status: 'cancelled',
          teacher: 'Profe Ana',
          confirmed_at: '2026-08-22T14:00:00Z',
          cancelled_at: '2026-08-22T14:15:00Z',
          student_plan_name: 'Privadas 10',
        },
      ],
    })

    render(<StudentPersonalizedClassesPage />)

    expect(await screen.findByText('Mis clases personalizadas')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Buscar...')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Todos los estados')).toBeInTheDocument()
    expect(screen.getAllByText('Profe Ana').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Profe Bea').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Anulada').length).toBeGreaterThan(0)
    expect(screen.getByText('1-3 de 3')).toBeInTheDocument()
  })
})
