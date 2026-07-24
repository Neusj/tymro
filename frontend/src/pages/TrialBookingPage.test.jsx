import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// La reserva marca has_used_trial=true en el backend; la sesión (user en AuthContext)
// debe refrescarse para que TrialClassBanner desaparezca al volver a la app (misma
// mecánica que RutReminderBanner: refreshMe tras guardar).
const refreshMe = vi.fn()
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'student' }, logout: vi.fn(), refreshMe }),
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
  id: 7, name: 'Yoga', start_datetime: '2026-08-01T10:00:00Z',
  branch_name: 'Centro', seats_left: 5,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TrialBookingPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  registrationApi.listTrialClasses.mockResolvedValue([CLASS])
  registrationApi.bookTrial.mockResolvedValue({})
})

describe('TrialBookingPage', () => {
  it('tras reservar con éxito refresca la sesión (/me) para apagar el banner de prueba', async () => {
    renderPage()

    const bookBtn = await screen.findByRole('button', { name: /agendar/i })
    await userEvent.click(bookBtn)

    await waitFor(() => expect(registrationApi.bookTrial).toHaveBeenCalledWith(7))
    await waitFor(() => expect(refreshMe).toHaveBeenCalled())
    // Confirmación visible (no rompió la UX de éxito).
    expect(await screen.findByText(/reserva confirmada/i)).toBeInTheDocument()
  })

  it('si la reserva falla, NO refresca la sesión y muestra el error', async () => {
    registrationApi.bookTrial.mockRejectedValue({ response: { data: { detail: 'Sin cupos.' } } })
    renderPage()

    const bookBtn = await screen.findByRole('button', { name: /agendar/i })
    await userEvent.click(bookBtn)

    expect(await screen.findByText(/sin cupos/i)).toBeInTheDocument()
    expect(refreshMe).not.toHaveBeenCalled()
  })
})
