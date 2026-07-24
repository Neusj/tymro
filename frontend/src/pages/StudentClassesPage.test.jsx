import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La página llama a estos módulos al montar (loadData). Los mockeamos para que
// resuelvan vacío y el árbol se renderice sin red real.
vi.mock('../api/client', () => ({
  classesApi: { list: vi.fn() },
  enrollmentsApi: { my: vi.fn(), create: vi.fn(), cancel: vi.fn() },
  recurringEnrollmentsApi: { my: vi.fn(), update: vi.fn() },
  classTemplatesApi: { recurringEnroll: vi.fn() },
  getMyPlan: vi.fn(),
}))

import { classesApi, enrollmentsApi, recurringEnrollmentsApi, getMyPlan } from '../api/client'
import StudentClassesPage from './StudentClassesPage'

function renderPage(mode = 'available') {
  return render(
    <MemoryRouter>
      <StudentClassesPage mode={mode} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.list.mockResolvedValue([])
  enrollmentsApi.my.mockResolvedValue([])
  recurringEnrollmentsApi.my.mockResolvedValue([])
  getMyPlan.mockResolvedValue(null)
  // jsdom no implementa matchMedia. Lo hacemos "query-aware": escritorio (min-width)
  // → true, para que FilterPanel abra y muestre los chips; DataTable (max-width)
  // → false, para que renderice la tabla de escritorio.
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'),
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
})

afterEach(() => {
  delete window.matchMedia
})

describe('StudentClassesPage — rango por defecto (#18)', () => {
  it('al montar, la lista de clases disponibles arranca en el rango de la semana actual', async () => {
    renderPage('available')
    // Deja que el fetch inicial se resuelva (evita warnings de act).
    await waitFor(() => expect(classesApi.list).toHaveBeenCalled())

    const semana = screen.getByRole('button', { name: 'Semana' })
    const hoy = screen.getByRole('button', { name: 'Hoy' })
    // "Semana" activo por defecto (no arranca mostrando todo/2 años).
    expect(semana).toHaveClass('bg-brand-blue/20')
    expect(hoy).not.toHaveClass('bg-brand-blue/20')
  })
})

// Una clase reservable dentro de la semana actual (para que pase el filtro por
// defecto), sin reserva activa y con plan con saldo → botón "Reservar" habilitado.
const FUTURE_ISO = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString()

function seedReservableClass() {
  classesApi.list
    .mockResolvedValueOnce([
      {
        id: 101,
        name: 'Yoga',
        status: 'scheduled',
        start_datetime: FUTURE_ISO,
        end_datetime: FUTURE_ISO,
        capacity: 10,
        enrollments_count: 0,
        branch_name: 'Sede',
        teacher_name: 'Prof',
        discipline_name: 'Yoga',
        class_template: null,
      },
    ])
    .mockResolvedValueOnce([])
  enrollmentsApi.my.mockResolvedValue([])
  recurringEnrollmentsApi.my.mockResolvedValue([])
  getMyPlan.mockResolvedValue({ total_classes: 10, classes_used: 0 })
  enrollmentsApi.create.mockResolvedValue({})
}

describe('StudentClassesPage — confirmar antes de reservar (#24)', () => {
  beforeEach(() => {
    // Vista de tarjetas (max-width): el botón "Reservar" (mobilePrimary) se
    // renderiza directo, sin el dropdown de acciones de la tabla de escritorio.
    window.matchMedia = (query) => ({
      matches: query.includes('max-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  it('reservar dispara un diálogo de confirmación; confirmar procede', async () => {
    seedReservableClass()
    renderPage('available')
    const user = userEvent.setup()

    const reservar = await screen.findByRole('button', { name: 'Reservar' })
    await user.click(reservar)

    // Aparece el diálogo "¿Seguro?" y todavía NO se reservó.
    expect(await screen.findByText(/¿seguro/i)).toBeInTheDocument()
    expect(enrollmentsApi.create).not.toHaveBeenCalled()

    // Confirmar dentro del diálogo → procede la reserva.
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Reservar' }))

    await waitFor(() =>
      expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 101, status: 'active' }),
    )
  })

  it('cancelar en el diálogo aborta la reserva', async () => {
    seedReservableClass()
    renderPage('available')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Reservar' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(enrollmentsApi.create).not.toHaveBeenCalled()
  })
})
