import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  attendanceEditConfigApi: { get: vi.fn(), update: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 } }),
}))

import { attendanceEditConfigApi } from '../api/client'
import GymAdminAttendanceEditConfigPage from './GymAdminAttendanceEditConfigPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminAttendanceEditConfigPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  attendanceEditConfigApi.get.mockResolvedValue({
    teacher_attendance_edit_limit_minutes: 30,
    teacher_enrollment_edit_limit_minutes: 30,
    allow_started_class_substitution: false,
  })
  attendanceEditConfigApi.update.mockResolvedValue({
    teacher_attendance_edit_limit_minutes: 15,
    teacher_enrollment_edit_limit_minutes: 45,
    allow_started_class_substitution: true,
  })
})

describe('GymAdminAttendanceEditConfigPage', () => {
  it('carga y guarda el limite en minutos', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('Configuracion de asistencia e inscripciones')).toBeInTheDocument()
    const input = await screen.findByLabelText('Tiempo limite para editar asistencia como profesor')
    expect(input).toHaveValue(30)
    const enrollmentInput = screen.getByLabelText('Tiempo limite para inscribir alumnos como profesor')
    expect(enrollmentInput).toHaveValue(30)
    const startedSubstitutionCheckbox = screen.getByLabelText(/Permitir suplencias con la clase ya comenzada/i)
    expect(startedSubstitutionCheckbox).not.toBeChecked()

    await user.clear(input)
    await user.type(input, '15')
    await user.clear(enrollmentInput)
    await user.type(enrollmentInput, '45')
    await user.click(startedSubstitutionCheckbox)
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() =>
      expect(attendanceEditConfigApi.update).toHaveBeenCalledWith(7, {
        teacher_attendance_edit_limit_minutes: 15,
        teacher_enrollment_edit_limit_minutes: 45,
        allow_started_class_substitution: true,
      }),
    )
    expect(await screen.findByText('Configuracion guardada correctamente.')).toBeInTheDocument()
  })

  it('rechaza valores negativos sin llamar al PUT', async () => {
    const user = userEvent.setup()
    renderPage()

    const input = await screen.findByLabelText('Tiempo limite para editar asistencia como profesor')
    await user.clear(input)
    await user.type(input, '-1')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/enteros entre 0 y 1440/i)).toBeInTheDocument()
    expect(attendanceEditConfigApi.update).not.toHaveBeenCalled()
  })
})
