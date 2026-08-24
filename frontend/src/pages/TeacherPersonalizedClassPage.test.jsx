import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import TeacherPersonalizedClassPage from './TeacherPersonalizedClassPage'
import { personalizedClassesApi } from '../api/client'

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(() => Promise.resolve('data:image/png;base64,qr')),
  },
}))

vi.mock('../api/client', () => ({
  personalizedClassesApi: {
    list: vi.fn(),
    createQr: vi.fn(),
    finish: vi.fn(),
  },
}))

describe('TeacherPersonalizedClassPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    personalizedClassesApi.list.mockResolvedValue({ count: 0, page: 1, page_size: 10, total_pages: 1, results: [] })
  })

  it('abre el modal con QR al comenzar clase', async () => {
    personalizedClassesApi.createQr.mockResolvedValue({
      check_in_url: 'https://app.test/attendance/check-in?token=abc',
      expires_in_seconds: 180,
      session: { id: 1, teacher: 'Profe Ana' },
    })

    render(<TeacherPersonalizedClassPage />)

    expect((await screen.findAllByText('No hay clases personalizadas')).length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Comenzar clase' }))

    expect(await screen.findByRole('dialog', { name: 'QR de clase personalizada' })).toBeInTheDocument()
    expect(screen.getByAltText('QR de clase personalizada')).toHaveAttribute('src', 'data:image/png;base64,qr')
    expect(screen.getByText('Vence en 3m 0s')).toBeInTheDocument()
    expect(personalizedClassesApi.createQr).toHaveBeenCalledTimes(1)
  })

  it('permite finalizar una clase en curso desde la lista', async () => {
    personalizedClassesApi.list
      .mockResolvedValueOnce({
        count: 1,
        page: 1,
        page_size: 10,
        total_pages: 1,
        results: [
          {
            id: 7,
            status: 'confirmed',
            student: 'Alumno Uno',
            teacher: 'Profe Ana',
            confirmed_at: '2026-08-24T14:00:00Z',
            can_finish: true,
          },
        ],
      })
      .mockResolvedValueOnce({
        count: 1,
        page: 1,
        page_size: 10,
        total_pages: 1,
        results: [
          {
            id: 7,
            status: 'finished',
            student: 'Alumno Uno',
            teacher: 'Profe Ana',
            confirmed_at: '2026-08-24T14:00:00Z',
            finished_at: '2026-08-24T15:00:00Z',
            can_finish: false,
          },
        ],
      })
    personalizedClassesApi.finish.mockResolvedValue({ id: 7, status: 'finished' })

    render(<TeacherPersonalizedClassPage />)

    await screen.findAllByRole('button', { name: 'Finalizar clase' })
    await userEvent.click(screen.getAllByRole('button', { name: 'Finalizar clase' })[0])

    await waitFor(() => expect(personalizedClassesApi.finish).toHaveBeenCalledWith(7))
    expect(await screen.findByText('Clase personalizada finalizada.')).toBeInTheDocument()
    expect(screen.getAllByText('Dictada').length).toBeGreaterThan(0)
  })
})
