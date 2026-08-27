import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  classesApi: { list: vi.fn() },
  classTemplatesApi: { retrieve: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin' } }),
}))

import { classesApi, classTemplatesApi } from '../api/client'
import GymAdminClassTemplateHistoryPage from './GymAdminClassTemplateHistoryPage'

let originalMatchMedia

function DetailProbe() {
  const { classId } = useParams()
  return <p>Detalle instancia {classId}</p>
}

function renderPage(initialEntry = '/gym-admin/class-templates/7/history') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/gym-admin/class-templates/:id/history" element={<GymAdminClassTemplateHistoryPage />} />
        <Route path="/gym-admin/classes/:classId" element={<DetailProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  originalMatchMedia = window.matchMedia
  window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
  classTemplatesApi.retrieve.mockResolvedValue({
    id: 7,
    name: 'Kick Boxing test',
    branch_name: 'Central',
    weekday: 3,
    start_time: '12:00:00',
    end_time: '13:00:00',
  })
  classesApi.list.mockResolvedValue([
    {
      id: 77,
      name: 'Kick Boxing test',
      teacher_name: 'Ana Prof',
      substitute_display_name: '',
      has_substitute: false,
      status: 'completed',
      start_datetime: '2026-08-20T12:00:00-04:00',
      end_datetime: '2026-08-20T13:00:00-04:00',
      enrollments_count: 8,
      present_attendances_count: 6,
      capacity: 20,
    },
  ])
})

afterEach(() => {
  if (originalMatchMedia) {
    window.matchMedia = originalMatchMedia
  } else {
    delete window.matchMedia
  }
})

describe('GymAdminClassTemplateHistoryPage', () => {
  it('carga instancias de una programacion y permite entrar al detalle guardado', async () => {
    renderPage('/gym-admin/class-templates/7/history?from=2026-08-01&to=2026-08-31')

    expect(await screen.findByRole('heading', { name: /historial - kick boxing test/i })).toBeInTheDocument()
    await waitFor(() =>
      expect(classesApi.list).toHaveBeenCalledWith({
        class_template: '7',
        ordering: '-start_datetime',
        start_date_from: '2026-08-01',
        start_date_to: '2026-08-31',
      }),
    )

    expect(screen.getByText('8/20')).toBeInTheDocument()
    expect(screen.getByText('6/8')).toBeInTheDocument()

    await userEvent.click(screen.getAllByText('Ana Prof')[0])

    expect(await screen.findByText('Detalle instancia 77')).toBeInTheDocument()
  })

  it('aplica filtros de fecha sin pedir otros endpoints', async () => {
    renderPage()

    await screen.findByRole('heading', { name: /historial - kick boxing test/i })
    await userEvent.type(screen.getByLabelText(/desde/i), '2026-08-01')
    await userEvent.type(screen.getByLabelText(/hasta/i), '2026-08-31')
    await userEvent.click(screen.getByRole('button', { name: /^filtrar$/i }))

    await waitFor(() =>
      expect(classesApi.list).toHaveBeenLastCalledWith({
        class_template: '7',
        ordering: '-start_datetime',
        start_date_from: '2026-08-01',
        start_date_to: '2026-08-31',
      }),
    )
  })
})
