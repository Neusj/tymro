import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  classesApi: {
    retrieve: vi.fn(),
    enrolledStudents: vi.fn(),
    enrollableStudents: vi.fn(),
    toggleAttendance: vi.fn(),
  },
  classTemplatesApi: {
    enrollableStudents: vi.fn(),
  },
  enrollmentsApi: {
    create: vi.fn(),
    cancel: vi.fn(),
  },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 7, role: 'teacher' } }),
}))

import { classesApi } from '../api/client'
import ClassAttendancePage from './ClassAttendancePage'

const GYM_CLASS = {
  id: 101,
  name: 'BJJ',
  branch_name: 'Sede',
  start_datetime: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  end_datetime: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  status: 'in_progress',
  teacher_attendance_edit_limit_minutes: 30,
  teacher_enrollment_edit_limit_minutes: 30,
}

const STUDENTS = [
  {
    student_id: 11,
    name: 'Ana Perez',
    email: 'ana@test.local',
    username: 'ana',
    attendance_status: 'absent',
  },
  {
    student_id: 12,
    name: 'Bruno Diaz',
    email: 'bruno@test.local',
    username: 'bruno',
    attendance_status: 'present',
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/teacher/classes/101/attendance']}>
      <Routes>
        <Route path="/teacher/classes/:id/attendance" element={<ClassAttendancePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.retrieve.mockResolvedValue(GYM_CLASS)
  classesApi.enrolledStudents.mockResolvedValue(STUDENTS)
  classesApi.enrollableStudents.mockResolvedValue([])
  classesApi.toggleAttendance.mockImplementation((_id, payload) => Promise.resolve({ status: payload.status }))
})

describe('ClassAttendancePage - boton de asistencia', () => {
  it('permite confirmar y quitar asistencia desde el boton rapido', async () => {
    const user = userEvent.setup()
    renderPage()

    const anaButton = await screen.findByRole('button', { name: 'Confirmar' })
    expect(screen.getByText('Ausente')).toBeInTheDocument()

    await user.click(anaButton)

    await waitFor(() =>
      expect(classesApi.toggleAttendance).toHaveBeenCalledWith('101', {
        student_id: 11,
        status: 'present',
      }),
    )
    expect(await screen.findAllByRole('button', { name: 'Quitar' })).toHaveLength(2)
    expect(screen.getAllByText('Presente')).toHaveLength(2)

    const brunoRow = screen.getByText('Bruno Diaz').closest('article')
    await user.click(within(brunoRow).getByRole('button', { name: 'Quitar' }))

    await waitFor(() =>
      expect(classesApi.toggleAttendance).toHaveBeenCalledWith('101', {
        student_id: 12,
        status: 'absent',
      }),
    )
    expect(classesApi.toggleAttendance).toHaveBeenCalledTimes(2)
    expect(screen.getAllByText('Presente')).toHaveLength(1)
    expect(screen.getAllByText('Ausente')).toHaveLength(1)
  })

  it('muestra el boton para inscribir alumnos al profesor en la vista de asistencia', async () => {
    renderPage()

    expect(await screen.findByRole('button', { name: 'Inscribir alumno' })).toBeInTheDocument()
  })
})
