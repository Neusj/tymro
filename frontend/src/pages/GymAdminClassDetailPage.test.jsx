import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La página llama a estos módulos al montar (loadData) y al guardar/ver historial
// de asistencia. Los mockeamos para controlar el roster y las respuestas del backend.
vi.mock('../api/client', () => ({
  classesApi: {
    retrieve: vi.fn(),
    saveAttendance: vi.fn(),
    getAttendanceHistory: vi.fn(),
  },
  enrollmentsApi: { create: vi.fn(), remove: vi.fn() },
  usersApi: { list: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin' } }),
}))

import { classesApi, usersApi } from '../api/client'
import GymAdminClassDetailPage from './GymAdminClassDetailPage'

function gymClassFixture(overrides = {}) {
  return {
    id: 55,
    name: 'Yoga AM',
    branch_name: 'Sede Centro',
    teacher_name: 'Prof. Ana',
    class_type_name: 'Grupal',
    discipline_name: 'Yoga',
    start_datetime: '2026-08-03T09:00:00-04:00',
    capacity: 10,
    enrollments: [
      { id: 1, student: 21, student_name: 'Bruno Diaz', student_email: 'bruno@test.local', status: 'active' },
      { id: 2, student: 22, student_name: 'Carla Ruiz', student_email: 'carla@test.local', status: 'active' },
    ],
    // Bruno ya tiene asistencia registrada ('present'); Carla no tiene registro
    // todavía → el default visual debe ser 'absent'.
    attendances: [
      {
        id: 100,
        student: 21,
        student_name: 'Bruno Diaz',
        status: 'present',
        source: 'manual',
        marked_by_username: 'profe1',
        marked_at: '2026-08-03T09:05:00-04:00',
      },
    ],
    ...overrides,
  }
}

function renderPage(classId = '55') {
  return render(
    <MemoryRouter initialEntries={[`/gym-admin/classes/${classId}`]}>
      <Routes>
        <Route path="/gym-admin/classes/:id" element={<GymAdminClassDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.retrieve.mockResolvedValue(gymClassFixture())
  usersApi.list.mockResolvedValue([])
  classesApi.saveAttendance.mockResolvedValue([])
  classesApi.getAttendanceHistory.mockResolvedValue([])
  // DataTable ("Alumnos inscritos") consulta matchMedia al montar; jsdom no lo
  // implementa. Mismo patrón que StudentClassesPage.test.jsx / GymAdminPlanMembershipsPage.test.jsx.
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

describe('GymAdminClassDetailPage — guardar asistencia (#10.2)', () => {
  it('manda el roster COMPLETO de inscritos activos con los status correctos al endpoint correcto', async () => {
    renderPage('55')
    const user = userEvent.setup()

    // El botón se habilita recién cuando el detalle de clase (con enrollments) cargó.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar asistencia' })).toBeEnabled())

    // Bruno_Diaz@21 debe quedar 'present' sin tocar (viene de attendances).
    // Carla@22 no tiene registro previo → arranca 'absent'; la marcamos 'Presente'.
    const attendanceSection = screen.getByRole('heading', { name: 'Asistencia' }).closest('section')
    const carlaRow = within(attendanceSection).getByText('Carla Ruiz').closest('div')
    await user.click(within(carlaRow).getByRole('button', { name: 'Presente' }))

    await user.click(screen.getByRole('button', { name: 'Guardar asistencia' }))

    await waitFor(() =>
      expect(classesApi.saveAttendance).toHaveBeenCalledWith('55', [
        { student_id: 21, status: 'present' },
        { student_id: 22, status: 'present' },
      ]),
    )
  })

  it('un alumno sin registro previo arranca visualmente en "Ausente" y se manda así si no se toca', async () => {
    renderPage('55')
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar asistencia' })).toBeEnabled())

    // Sin tocar nada: Bruno queda 'present' (su registro previo), Carla 'absent' (default).
    await user.click(screen.getByRole('button', { name: 'Guardar asistencia' }))

    await waitFor(() =>
      expect(classesApi.saveAttendance).toHaveBeenCalledWith('55', [
        { student_id: 21, status: 'present' },
        { student_id: 22, status: 'absent' },
      ]),
    )
  })
})

describe('GymAdminClassDetailPage — historial de correcciones (#10.2)', () => {
  it('renderiza cada corrección con anterior→nuevo (badges) y quién la hizo', async () => {
    classesApi.getAttendanceHistory.mockResolvedValue([
      {
        id: 1,
        attendance: 100,
        student: 21,
        student_name: 'Bruno Diaz',
        previous_status: 'absent',
        new_status: 'present',
        changed_by: 9,
        changed_by_username: 'admin_gym',
        changed_at: '2026-08-03T10:00:00-04:00',
        source: 'manual',
      },
    ])

    renderPage('55')
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar asistencia' })).toBeEnabled())

    await user.click(screen.getByRole('button', { name: /Historial de correcciones/i }))

    await waitFor(() => expect(classesApi.getAttendanceHistory).toHaveBeenCalledWith('55'))

    const historySection = screen.getByRole('button', { name: /Historial de correcciones/i }).closest('section')
    expect(await within(historySection).findByText('Bruno Diaz')).toBeInTheDocument()
    expect(within(historySection).getByText('Ausente')).toBeInTheDocument() // previous_status
    expect(within(historySection).getByText('Presente')).toBeInTheDocument() // new_status
    expect(within(historySection).getByText(/admin_gym/)).toBeInTheDocument()
    expect(within(historySection).getByText('Manual')).toBeInTheDocument()
  })

  it('un log con source "qr" (10.2-H1: pisada de QR) se etiqueta distinto del manual', async () => {
    classesApi.getAttendanceHistory.mockResolvedValue([
      {
        id: 2,
        attendance: 100,
        student: 21,
        student_name: 'Bruno Diaz',
        previous_status: 'absent',
        new_status: 'present',
        changed_by: 21,
        changed_by_username: 'bruno.diaz',
        changed_at: '2026-08-03T10:05:00-04:00',
        source: 'qr',
      },
    ])

    renderPage('55')
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar asistencia' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /Historial de correcciones/i }))
    await waitFor(() => expect(classesApi.getAttendanceHistory).toHaveBeenCalledWith('55'))

    const historySection = screen.getByRole('button', { name: /Historial de correcciones/i }).closest('section')
    expect(await within(historySection).findByText('QR')).toBeInTheDocument()
    expect(within(historySection).queryByText('Manual')).not.toBeInTheDocument()
  })

  it('con historial vacío muestra el texto de "sin correcciones"', async () => {
    classesApi.getAttendanceHistory.mockResolvedValue([])

    renderPage('55')
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar asistencia' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /Historial de correcciones/i }))

    expect(await screen.findByText('Sin correcciones registradas.')).toBeInTheDocument()
  })

  it('un rol distinto de gym_admin/superadmin recibe 403 y la sección lo muestra como error, no como vacío', async () => {
    const forbidden = { response: { status: 403, data: { detail: 'No tienes permisos para ver el historial de asistencia.' } } }
    classesApi.getAttendanceHistory.mockRejectedValue(forbidden)

    renderPage('55')
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Guardar asistencia' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /Historial de correcciones/i }))

    expect(await screen.findByText('No tienes permisos para ver el historial de asistencia.')).toBeInTheDocument()
    expect(screen.queryByText('Sin correcciones registradas.')).not.toBeInTheDocument()
  })
})
