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
  classTemplatesApi: { enrollableStudents: vi.fn() },
  enrollmentsApi: { create: vi.fn(), cancel: vi.fn() },
}))

let mockRole = 'gym_admin'
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}))

import { classesApi, classTemplatesApi, disciplinesApi, enrollmentsApi } from '../api/client'
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

const realClass = { ...projectedRow, id: 501, class_template: 77 }

const candidate = {
  id: 9,
  name: 'Ana Perez',
  username: 'ana',
  email: 'ana@gym.cl',
  available_classes: 5,
  has_available_classes: true,
  unlimited_classes: false,
}

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

async function clickEnroll(user) {
  await user.click(await screen.findByRole('button', { name: /inscribir alumnos/i }))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockRole = 'gym_admin'
  classesApi.byDate.mockResolvedValue([projectedRow])
  classesApi.enrolledStudents.mockResolvedValue([])
  classesApi.enrollableStudents.mockResolvedValue([])
  disciplinesApi.list.mockResolvedValue([])
  classTemplatesApi.enrollableStudents.mockResolvedValue([candidate])
  enrollmentsApi.create.mockResolvedValue({ id: 1, gym_class: 501 })
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

  it('no ofrece inscribir en una fila proyectada de una fecha pasada', async () => {
    const user = userEvent.setup()
    // `by_date` proyecta filas para CUALQUIER fecha y el selector de dia deja ir al pasado:
    // ahi el POST daria 400 garantizado, asi que el boton no debe invitar al callejon.
    classesApi.byDate.mockResolvedValue([{ ...projectedRow, id: 'virtual:77:2020-01-06' }])
    renderPage()
    await openRowActions(user)

    expect(await screen.findByRole('button', { name: /inscribir alumnos/i })).toBeDisabled()
  })

  it('abre el picker contra la SERIE y no crea la clase', async () => {
    const user = userEvent.setup()
    renderPage()
    await openRowActions(user)

    await clickEnroll(user)

    // Mirar no materializa: el roster sale de la serie, no de una clase que no existe.
    await waitFor(() => {
      expect(classTemplatesApi.enrollableStudents).toHaveBeenCalledWith(77)
    })
    expect(classesApi.enrollableStudents).not.toHaveBeenCalled()
    expect(enrollmentsApi.create).not.toHaveBeenCalled()
  })

  it('inscribir materializa e inscribe en un solo acto', async () => {
    const user = userEvent.setup()
    renderPage()
    await openRowActions(user)
    await clickEnroll(user)

    await user.click((await screen.findAllByRole('checkbox')).slice(-1)[0])
    await user.click(await screen.findByRole('button', { name: /inscribir seleccionados/i }))

    // El mismo contrato que ya usa el alumno al reservar: la clase nace CON la inscripcion,
    // que es donde corresponde que se descuente el plan.
    await waitFor(() => {
      expect(enrollmentsApi.create).toHaveBeenCalledWith({
        class_template_id: 77,
        date: PROJECTED_DATE,
        student: candidate.id,
        status: 'active',
      })
    })
  })

  it('tras inscribir, el listado se recarga para que la fila deje de estar proyectada', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalledTimes(1))
    await openRowActions(user)
    await clickEnroll(user)

    await user.click((await screen.findAllByRole('checkbox')).slice(-1)[0])
    await user.click(await screen.findByRole('button', { name: /inscribir seleccionados/i }))

    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalledTimes(2))
  })

  it('muestra el error del backend si el picker de la serie falla', async () => {
    const user = userEvent.setup()
    classTemplatesApi.enrollableStudents.mockRejectedValue({
      response: { data: { detail: 'No tienes permisos para listar alumnos inscribibles en esta serie.' } },
    })
    renderPage()
    await openRowActions(user)

    await clickEnroll(user)

    expect(await screen.findByText(/no tienes permisos para listar alumnos/i)).toBeInTheDocument()
  })

  it('una clase real sigue usando el picker de la clase', async () => {
    const user = userEvent.setup()
    classesApi.byDate.mockResolvedValue([realClass])
    renderPage()
    await openRowActions(user)

    await clickEnroll(user)

    await waitFor(() => expect(classesApi.enrollableStudents).toHaveBeenCalledWith(501))
    expect(classTemplatesApi.enrollableStudents).not.toHaveBeenCalled()
  })
})
