import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  classesApi: {
    byDate: vi.fn(),
    cancel: vi.fn(),
    completeEarly: vi.fn(),
    reactivate: vi.fn(),
    remove: vi.fn(),
    bulkClose: vi.fn(),
    enrolledStudents: vi.fn(),
    enrollableStudents: vi.fn(),
  },
  disciplinesApi: { list: vi.fn() },
  classTemplatesApi: { materialize: vi.fn() },
  enrollmentsApi: { create: vi.fn(), cancel: vi.fn() },
}))

let mockRole = 'gym_admin'
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}))

import { classesApi, classTemplatesApi, disciplinesApi } from '../api/client'
import GymAdminClassesPage from './GymAdminClassesPage'

const PROJECTED_DATE = '2026-09-15'

// Fila proyectada tal como la devuelve `by_date`: id sintetico `virtual:<serie>:<fecha>`,
// sin PK real detras.
const projectedRow = {
  id: `virtual:77:${PROJECTED_DATE}`,
  name: 'Boxeo',
  class_template: 77,
  class_template_name: 'Boxeo',
  branch_name: 'Central',
  teacher_name: 'Emanuel Aguilera',
  class_type_name: 'Grupal',
  discipline_name: 'Boxeo',
  start_datetime: `${PROJECTED_DATE}T07:00:00-03:00`,
  end_datetime: `${PROJECTED_DATE}T08:00:00-03:00`,
  capacity: 10,
  enrollments_count: 0,
  status: 'scheduled',
}

const materializedClass = { ...projectedRow, id: 501, class_template: 77 }

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminClassesPage />
    </MemoryRouter>,
  )
}

// Las acciones de fila viven detras del engranaje de DataTable (`RowActionsDropdown`),
// igual que en la app real: hay que abrirlo antes de ver los botones.
async function openRowActions(user) {
  const gears = await screen.findAllByRole('button', { name: /abrir acciones/i })
  await user.click(gears[0])
}

beforeEach(() => {
  vi.clearAllMocks()
  mockRole = 'gym_admin'
  classesApi.byDate.mockResolvedValue([projectedRow])
  classesApi.enrolledStudents.mockResolvedValue([])
  classesApi.enrollableStudents.mockResolvedValue([])
  disciplinesApi.list.mockResolvedValue([])
  classTemplatesApi.materialize.mockResolvedValue(materializedClass)
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  })
})

describe('inscripcion sobre una clase proyectada', () => {
  it('ofrece inscribir alumnos en una fila proyectada', async () => {
    const user = userEvent.setup()
    renderPage()
    await openRowActions(user)

    expect(await screen.findByRole('button', { name: /inscribir alumnos/i })).toBeEnabled()
  })

  it('materializa la serie en esa fecha antes de abrir el modal', async () => {
    const user = userEvent.setup()
    renderPage()
    await openRowActions(user)

    await user.click(await screen.findByRole('button', { name: /inscribir alumnos/i }))

    await waitFor(() => {
      expect(classTemplatesApi.materialize).toHaveBeenCalledWith(77, { date: PROJECTED_DATE })
    })
    // El modal tiene que abrirse contra la PK real que devolvio el backend, no contra
    // el id sintetico: es lo unico que hace usables enrollable-students / enrolled-students.
    await waitFor(() => {
      expect(classesApi.enrollableStudents).toHaveBeenCalledWith(501)
    })
  })

  it('recarga el listado para que la fila deje de estar proyectada', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalledTimes(1))
    await openRowActions(user)

    await user.click(await screen.findByRole('button', { name: /inscribir alumnos/i }))

    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalledTimes(2))
  })

  it('muestra el error del backend y no abre el modal si la fecha esta fuera de rango', async () => {
    const user = userEvent.setup()
    classTemplatesApi.materialize.mockRejectedValue({
      response: { data: { detail: 'No puedes reservar con más de 7 días de anticipación.' } },
    })
    renderPage()
    await openRowActions(user)

    await user.click(await screen.findByRole('button', { name: /inscribir alumnos/i }))

    expect(await screen.findByText(/más de 7 días de anticipación/i)).toBeInTheDocument()
    expect(classesApi.enrollableStudents).not.toHaveBeenCalled()
  })

  it('no ofrece inscribir en una fila proyectada de una fecha pasada', async () => {
    const user = userEvent.setup()
    // `by_date` proyecta filas para CUALQUIER fecha y el selector de dia deja ir al pasado:
    // ahi el POST daria 400 garantizado, asi que el boton no debe invitar al callejon.
    classesApi.byDate.mockResolvedValue([
      { ...projectedRow, id: 'virtual:77:2020-01-06' },
    ])
    renderPage()
    await openRowActions(user)

    expect(await screen.findByRole('button', { name: /inscribir alumnos/i })).toBeDisabled()
  })

  it('muestra el motivo real cuando el backend rechaza por un campo y no por detail', async () => {
    const user = userEvent.setup()
    // Solo el error de ventana viene como `detail`; los otros cuatro llegan por campo.
    classTemplatesApi.materialize.mockRejectedValue({
      response: { data: { date: ['La fecha no corresponde al dia de la plantilla.'] } },
    })
    renderPage()
    await openRowActions(user)

    await user.click(await screen.findByRole('button', { name: /inscribir alumnos/i }))

    expect(await screen.findByText(/no corresponde al dia de la plantilla/i)).toBeInTheDocument()
  })

  it('no materializa cuando la clase ya es real', async () => {
    const user = userEvent.setup()
    classesApi.byDate.mockResolvedValue([materializedClass])
    renderPage()
    await openRowActions(user)

    await user.click(await screen.findByRole('button', { name: /inscribir alumnos/i }))

    await waitFor(() => expect(classesApi.enrollableStudents).toHaveBeenCalledWith(501))
    expect(classTemplatesApi.materialize).not.toHaveBeenCalled()
  })
})
