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
    personalizedClassesApi.list.mockResolvedValue([
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
    ])

    render(<StudentPersonalizedClassesPage />)

    expect(await screen.findByText('Mis clases personalizadas')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'En curso' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Dictadas' })).toBeInTheDocument()
    expect(screen.getByText('Profe Ana')).toBeInTheDocument()
    expect(screen.getByText('Profe Bea')).toBeInTheDocument()
  })
})
