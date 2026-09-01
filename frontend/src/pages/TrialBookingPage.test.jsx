import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La reserva marca has_used_trial=true en el backend; la sesión (user en AuthContext)
// debe refrescarse para que TrialClassBanner desaparezca al volver a la app (misma
// mecánica que RutReminderBanner: refreshMe tras guardar).
const refreshMe = vi.fn()
let mockUser
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, logout: vi.fn(), refreshMe }),
}))
vi.mock('../api/client', () => ({
  registrationApi: {
    listTrialClasses: vi.fn(),
    bookTrial: vi.fn(),
  },
}))

import { registrationApi } from '../api/client'
import TrialBookingPage from './TrialBookingPage'

const CLASS = {
  id: 7, name: 'Yoga', start_datetime: '2026-08-01T10:00:00',
  branch_name: 'Centro', teacher_name: 'Ana', discipline_name: 'Yoga', seats_left: 5,
}

const VIRTUAL_CLASS = {
  id: 'virtual:12:2026-08-02',
  class_template: 12,
  is_virtual: true,
  name: 'Boxeo',
  start_datetime: '2026-08-02T09:30:00',
  branch_name: 'Centro',
  teacher_name: 'Eduardo',
  discipline_name: 'Boxeo',
  seats_left: 20,
}

const listPayload = (overrides = {}) => ({
  results: [CLASS],
  count: 1,
  limit: 10,
  has_more: false,
  window_days: 7,
  filters: {
    branches: [{ id: 1, name: 'Centro' }, { id: 2, name: 'Norte' }],
    disciplines: [{ id: 3, name: 'Yoga' }],
    teachers: [{ id: 4, name: 'Ana' }],
  },
  ...overrides,
})

function renderPage() {
  return render(
    <MemoryRouter>
      <TrialBookingPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockUser = { role: 'student', trial_eligible: true, has_used_trial: false }
  vi.clearAllMocks()
  registrationApi.listTrialClasses.mockResolvedValue(listPayload())
  registrationApi.bookTrial.mockResolvedValue({})
})

afterEach(() => {
  vi.useRealTimers()
})

describe('TrialBookingPage', () => {
  it('carga solo el dia seleccionado con limite y metadata de filtros', async () => {
    renderPage()

    await screen.findByRole('button', { name: /reservar esta clase/i })

    expect(registrationApi.listTrialClasses).toHaveBeenCalledWith(expect.objectContaining({
      date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      limit: 10,
      include_filters: 1,
    }))
    expect(screen.getByRole('searchbox', { name: /buscar clase/i })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /disciplina/i })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /sucursal/i })).toBeInTheDocument()
    expect(screen.getByText(/10:00/)).toBeInTheDocument()
    expect(screen.getByText(/5 cupos/i)).toBeInTheDocument()
  })

  it('debouncea busqueda y la envia al servidor', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /reservar esta clase/i })

    await user.type(screen.getByRole('searchbox', { name: /buscar clase/i }), 'ana')
    expect(registrationApi.listTrialClasses).toHaveBeenCalledTimes(1)

    await waitFor(() => expect(registrationApi.listTrialClasses).toHaveBeenCalledWith(expect.objectContaining({ q: 'ana' })))
  })

  it('aplica filtro de sucursal server-side', async () => {
    const user = userEvent.setup()
    renderPage()
    const branchSelect = await screen.findByRole('combobox', { name: /sucursal/i })

    await user.selectOptions(branchSelect, '2')

    await waitFor(() => expect(registrationApi.listTrialClasses).toHaveBeenCalledWith(expect.objectContaining({ branch_id: '2' })))
  })

  it('muestra estado sin resultados y permite limpiar filtros', async () => {
    registrationApi.listTrialClasses
      .mockResolvedValueOnce(listPayload())
      .mockResolvedValueOnce(listPayload({ results: [], count: 0, has_more: false }))
      .mockResolvedValueOnce(listPayload())
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(await screen.findByRole('combobox', { name: /disciplina/i }), '3')

    expect(await screen.findByText(/no hay resultados/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /limpiar filtros/i }))

    await waitFor(() => expect(registrationApi.listTrialClasses).toHaveBeenLastCalledWith(expect.objectContaining({
      discipline_id: undefined,
    })))
  })

  it('tras reservar con éxito refresca la sesión (/me) para apagar el banner de prueba', async () => {
    renderPage()

    const bookBtn = await screen.findByRole('button', { name: /reservar esta clase/i })
    await userEvent.click(bookBtn)

    await waitFor(() => expect(registrationApi.bookTrial).toHaveBeenCalledWith(CLASS))
    await waitFor(() => expect(refreshMe).toHaveBeenCalled())
    // Confirmación visible (no rompió la UX de éxito).
    expect(await screen.findByText(/reserva confirmada/i)).toBeInTheDocument()
  })

  it('reserva clases proyectadas usando el objeto de la proyeccion', async () => {
    registrationApi.listTrialClasses.mockResolvedValue(listPayload({ results: [VIRTUAL_CLASS] }))
    renderPage()

    const bookBtn = await screen.findByRole('button', { name: /reservar esta clase/i })
    await userEvent.click(bookBtn)

    await waitFor(() => expect(registrationApi.bookTrial).toHaveBeenCalledWith(VIRTUAL_CLASS))
    expect(await screen.findByText(/reserva confirmada/i)).toBeInTheDocument()
  })

  it('valida que el buscador de fecha no salga de la ventana configurada', async () => {
    registrationApi.listTrialClasses.mockResolvedValue(listPayload({ window_days: 2 }))
    renderPage()
    await screen.findByRole('button', { name: /reservar esta clase/i })

    const outside = new Date()
    outside.setDate(outside.getDate() + 5)
    fireEvent.change(screen.getByLabelText(/buscar por fecha/i), {
      target: { value: outside.toISOString().slice(0, 10) },
    })

    expect(await screen.findByText(/elige una fecha entre/i)).toBeInTheDocument()
    expect(registrationApi.listTrialClasses).toHaveBeenCalledTimes(1)
  })

  it('si la reserva falla, NO refresca la sesión y muestra el error', async () => {
    registrationApi.bookTrial.mockRejectedValue({ response: { data: { detail: 'Sin cupos.' } } })
    renderPage()

    const bookBtn = await screen.findByRole('button', { name: /reservar esta clase/i })
    await userEvent.click(bookBtn)

    expect(await screen.findByText(/sin cupos/i)).toBeInTheDocument()
    expect(refreshMe).not.toHaveBeenCalled()
  })

  it('si la cuenta no tiene prueba gratis, no carga horarios ni ofrece agendar', async () => {
    mockUser = { role: 'student', trial_eligible: false, has_used_trial: false }
    renderPage()

    expect(await screen.findByText(/clase de prueba no disponible/i)).toBeInTheDocument()
    expect(screen.getByText(/no tiene una clase de prueba gratis disponible/i)).toBeInTheDocument()
    expect(registrationApi.listTrialClasses).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /reservar esta clase/i })).not.toBeInTheDocument()
  })
})
