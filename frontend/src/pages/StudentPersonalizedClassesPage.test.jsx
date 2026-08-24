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

  it('muestra clases personalizadas en curso y dictadas del alumno', async () => {
    personalizedClassesApi.list.mockResolvedValue({
      count: 2,
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
      ],
    })

    render(<StudentPersonalizedClassesPage />)

    expect(await screen.findByText('Mis clases personalizadas')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Buscar...')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Todos los estados')).toBeInTheDocument()
    expect(screen.getAllByText('Profe Ana').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Profe Bea').length).toBeGreaterThan(0)
    expect(screen.getByText('1-2 de 2')).toBeInTheDocument()
  })
})
