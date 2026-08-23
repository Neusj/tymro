import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  classesApi: {
    list: vi.fn(),
    byDate: vi.fn(),
    coverable: vi.fn(),
    claimSubstitution: vi.fn(),
    releaseSubstitution: vi.fn(),
    enrollableStudents: vi.fn(),
    enrolledStudents: vi.fn(),
    reactivate: vi.fn(),
  },
  enrollmentsApi: { create: vi.fn(), cancel: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 777, role: 'teacher' } }),
}))

import { classesApi } from '../api/client'
import TeacherClassesPage from './TeacherClassesPage'

const DAY = 24 * 60 * 60 * 1000

const GYM_CLASS = {
  id: 101,
  name: 'BJJ Fundamentos',
  branch_name: 'Sede',
  class_type_name: 'Regular',
  discipline_name: 'BJJ',
  status: 'scheduled',
  capacity: 10,
  enrollments_count: 0,
  start_datetime: new Date(Date.now() + DAY).toISOString(),
  end_datetime: new Date(Date.now() + DAY + 3600000).toISOString(),
}

// Fila tal como la manda el roster (`enrollable-students`) despues de 7.3.
function candidate(overrides = {}) {
  return {
    id: 5,
    username: 'ana',
    name: 'Ana Perez',
    email: 'ana@test.local',
    available_classes: 8,
    has_available_classes: true,
    unlimited_classes: false,
    plan_status: 'active',
    plan_status_label: 'Vigente',
    plan_days_to_expiry: 20,
    plan_reason_code: null,
    plan_expiry_alert_level: 'safe',
    plan_expiry_alert_message: '20 dias vigentes',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.list.mockResolvedValue([GYM_CLASS])
  classesApi.byDate.mockImplementation((date, params) => classesApi.list(params))
  classesApi.coverable.mockResolvedValue([])
  classesApi.claimSubstitution.mockResolvedValue({})
  classesApi.releaseSubstitution.mockResolvedValue({})
  classesApi.reactivate.mockResolvedValue({})
  classesApi.enrolledStudents.mockResolvedValue([])
  classesApi.enrollableStudents.mockResolvedValue([candidate()])
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

// DataTable pinta la tabla de escritorio Y las tarjetas móviles a la vez (las alterna por
// CSS), asi que cada celda y cada acción aparecen dos veces en el DOM.
const shown = (text) => screen.queryAllByText(text).length
const renderTeacherClassesPage = (mode) =>
  render(
    <MemoryRouter>
      <TeacherClassesPage mode={mode} />
    </MemoryRouter>,
  )

async function openEnrollModal() {
  renderTeacherClassesPage('upcoming')
  await waitFor(() => expect(shown('BJJ Fundamentos')).toBeGreaterThan(0))
  // Las acciones de fila viven detrás del engranaje de DataTable (RowActionsDropdown).
  await userEvent.click(screen.getAllByRole('button', { name: 'Abrir acciones' })[0])
  await userEvent.click(await screen.findByRole('button', { name: 'Inscribir alumnos' }))
  await waitFor(() => expect(shown('Ana Perez')).toBeGreaterThan(0))
  return screen.getAllByText('Ana Perez')[0].closest('label')
}

describe('TeacherClassesPage — badge de plan en el roster', () => {
  it('pinta el aviso del backend en vez de reescribirlo', async () => {
    const row = await openEnrollModal()

    expect(within(row).getByText('20 dias vigentes')).toBeInTheDocument()
  })

  it('no dice "Sin plan" a un alumno cuyo plan se quedó sin clases', async () => {
    // El `else` de :76 mandaba a "Sin plan" cualquier estado que no reconociera, y
    // exhausted/enrollment_fee_unpaid eran exactamente eso.
    classesApi.enrollableStudents.mockResolvedValue([
      candidate({
        available_classes: 0,
        has_available_classes: false,
        plan_status: 'exhausted',
        plan_status_label: 'Sin clases disponibles',
        plan_reason_code: 'plan_unavailable',
        plan_expiry_alert_level: 'danger',
        plan_expiry_alert_message: 'Sin clases disponibles',
      }),
    ])

    const row = await openEnrollModal()

    expect(within(row).getByText('Sin clases disponibles')).toBeInTheDocument()
    expect(shown('Sin plan')).toBe(0)
  })

  it('no ofrece inscribir a quien debe la matrícula, aunque tenga saldo', async () => {
    classesApi.enrollableStudents.mockResolvedValue([
      candidate({
        available_classes: 8,
        has_available_classes: false,
        plan_status: 'enrollment_fee_unpaid',
        plan_status_label: 'Matrícula impaga',
        plan_reason_code: 'enrollment_fee_unpaid',
        plan_expiry_alert_level: 'danger',
        plan_expiry_alert_message: 'Matrícula impaga',
      }),
    ])

    const row = await openEnrollModal()

    expect(within(row).getByRole('checkbox')).toBeDisabled()
    // El saldo se sigue diciendo tal cual: las 8 clases existen, lo que falta es la matrícula.
    expect(within(row).getByText('8 clases')).toBeInTheDocument()
    expect(within(row).getByText('Matrícula impaga')).toBeInTheDocument()
  })
})

describe('TeacherClassesPage - vista completa', () => {
  it('lista todas las clases del profesor sin filtrar por dia', async () => {
    renderTeacherClassesPage('all')

    await waitFor(() => expect(shown('BJJ Fundamentos')).toBeGreaterThan(0))

    expect(classesApi.list).toHaveBeenCalledWith({
      ordering: 'start_datetime',
      teacher_scope: 'mine',
    })
    expect(classesApi.byDate).not.toHaveBeenCalled()
    expect(screen.getByText(/Mis clases/)).toBeInTheDocument()
  })

  it('lista clases pasadas completadas en mis clases por fecha', async () => {
    classesApi.list.mockResolvedValue([
      {
        ...GYM_CLASS,
        id: 404,
        status: 'completed',
        start_datetime: new Date(Date.now() - DAY).toISOString(),
        end_datetime: new Date(Date.now() - DAY + 3600000).toISOString(),
      },
    ])

    renderTeacherClassesPage('upcoming')

    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalledWith(expect.any(String), {
      ordering: 'start_datetime',
      teacher_scope: 'mine',
    }))
    await waitFor(() => expect(shown('BJJ Fundamentos')).toBeGreaterThan(0))
  })
})

describe('TeacherClassesPage — suplencias disponibles', () => {
  it('muestra solo clases disponibles para cubrir', async () => {
    classesApi.list.mockResolvedValue([])
    classesApi.coverable.mockResolvedValue([
      {
        ...GYM_CLASS,
        id: 202,
        name: 'Boxeo',
        teacher_name: 'Prof. Matias',
        has_substitute: true,
        substitute_teacher: 777,
        substitute_display_name: 'Yo Profesor',
        can_claim_substitution: false,
      },
    ])

    renderTeacherClassesPage('coverable')

    await waitFor(() => expect(classesApi.coverable).toHaveBeenCalled())
    expect(shown('Boxeo')).toBe(0)
    expect(screen.queryByRole('button', { name: 'Dejar de cubrir' })).not.toBeInTheDocument()
  })

  it('mantiene la accion de cubrir cuando la clase sigue disponible', async () => {
    const user = userEvent.setup()
    classesApi.list.mockResolvedValue([])
    classesApi.coverable.mockResolvedValue([
      {
        ...GYM_CLASS,
        id: 203,
        name: 'Kick Boxing',
        teacher_name: 'Prof. Matias',
        has_substitute: false,
        substitute_display_name: '',
        can_claim_substitution: true,
        can_release_substitution: false,
      },
    ])

    renderTeacherClassesPage('coverable')

    await waitFor(() => expect(shown('Kick Boxing')).toBeGreaterThan(0))
    await user.click(screen.getAllByRole('button', { name: 'Cubrir' })[0])
    await user.click(within(await screen.findByRole('dialog', { name: 'Cubrir' })).getByRole('button', { name: 'Cubrir' }))

    await waitFor(() => expect(classesApi.claimSubstitution).toHaveBeenCalledWith(203))
  })

  it('abre el detalle directo desde clases por cubrir', async () => {
    const user = userEvent.setup()
    classesApi.list.mockResolvedValue([])
    classesApi.coverable.mockResolvedValue([
      {
        ...GYM_CLASS,
        id: 204,
        name: 'Muay Thai',
        teacher_name: 'Prof. Matias',
        has_substitute: false,
        substitute_display_name: '',
        can_claim_substitution: true,
        can_release_substitution: false,
      },
    ])

    renderTeacherClassesPage('coverable')

    await waitFor(() => expect(shown('Muay Thai')).toBeGreaterThan(0))
    const detailButtons = screen.getAllByRole('button', { name: 'Detalle' })
    await user.click(detailButtons[detailButtons.length - 1])

    expect(await screen.findByRole('dialog', { name: /Detalles · Muay Thai/ })).toBeInTheDocument()
  })

  it('permite dejar de cubrir una suplencia tomada desde mis clases', async () => {
    const user = userEvent.setup()
    classesApi.list.mockResolvedValue([
      {
        ...GYM_CLASS,
        id: 205,
        name: 'Boxeo tomado',
        has_substitute: true,
        substitute_teacher: 777,
        substitute_display_name: 'Yo Profesor',
        can_release_substitution: true,
      },
    ])

    renderTeacherClassesPage('upcoming')

    await waitFor(() => expect(shown('Boxeo tomado')).toBeGreaterThan(0))
    await user.click(screen.getAllByRole('button', { name: 'Abrir acciones' })[0])
    await user.click(await screen.findByRole('button', { name: 'Dejar de cubrir' }))
    await user.click(within(screen.getByRole('dialog', { name: 'Dejar de cubrir' })).getByRole('button', { name: 'Dejar de cubrir' }))

    await waitFor(() => expect(classesApi.releaseSubstitution).toHaveBeenCalledWith(205))
  })
})

describe('TeacherClassesPage - reabrir canceladas', () => {
  it('incluye canceladas en proximas y permite reabrirlas sin restaurar reservas', async () => {
    const user = userEvent.setup()
    classesApi.list.mockResolvedValue([{ ...GYM_CLASS, id: 303, status: 'cancelled', enrollments_count: 0 }])

    renderTeacherClassesPage('upcoming')

    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalledWith(expect.any(String), {
      ordering: 'start_datetime',
      teacher_scope: 'mine',
    }))
    await waitFor(() => expect(shown('BJJ Fundamentos')).toBeGreaterThan(0))
    await user.click(screen.getAllByRole('button', { name: 'Abrir acciones' })[0])
    await user.click(await screen.findByRole('button', { name: 'Reabrir clase' }))

    expect(screen.getByText(/Las reservas canceladas no se restauraran automaticamente/)).toBeInTheDocument()

    await user.click(within(screen.getByRole('dialog', { name: 'Reabrir clase' })).getByRole('button', { name: 'Reabrir clase' }))

    await waitFor(() => expect(classesApi.reactivate).toHaveBeenCalledWith(303))
  })
})
