import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La pagina carga estos modulos al montar (loadData).
vi.mock('../api/client', () => ({
  advanceClassWindowsApi: { run: vi.fn() },
  branchesApi: { list: vi.fn() },
  classesApi: { byDate: vi.fn(), bulkClose: vi.fn() },
  classTemplatesApi: { list: vi.fn(), generate: vi.fn(), update: vi.fn(), remove: vi.fn(), bulkAction: vi.fn(), create: vi.fn(), reactivateFutureCancelled: vi.fn() },
  classTypesApi: { list: vi.fn() },
  disciplinesApi: { list: vi.fn() },
  usersApi: { list: vi.fn() },
}))

let mockRole = 'gym_admin'
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}))

import {
  advanceClassWindowsApi,
  branchesApi,
  classesApi,
  classTemplatesApi,
  classTypesApi,
  disciplinesApi,
  usersApi,
} from '../api/client'
import GymAdminClassTemplatesPage from './GymAdminClassTemplatesPage'

let originalScrollIntoView
let scrollIntoViewMock

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminClassTemplatesPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockRole = 'gym_admin'
  originalScrollIntoView = Element.prototype.scrollIntoView
  scrollIntoViewMock = vi.fn()
  Element.prototype.scrollIntoView = scrollIntoViewMock
  classesApi.byDate.mockResolvedValue([])
  classTemplatesApi.list.mockResolvedValue([])
  branchesApi.list.mockResolvedValue([])
  usersApi.list.mockResolvedValue([])
  classTypesApi.list.mockResolvedValue([])
  disciplinesApi.list.mockResolvedValue([])
  advanceClassWindowsApi.run.mockResolvedValue({ instances_created: 0 })
  // DataTable consulta matchMedia al montar; jsdom no lo implementa. Mismo patron
  // que GymAdminClassDetailPage.test.jsx / GymAdminPlanMembershipsPage.test.jsx.
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
  if (originalScrollIntoView) {
    Element.prototype.scrollIntoView = originalScrollIntoView
  } else {
    delete Element.prototype.scrollIntoView
  }
})

async function openCreateForm() {
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /^crear clase$/i }))
  await screen.findByLabelText(/nombre visible/i)
}

async function openScheduleTab() {
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /^programaci/i }))
}

describe('GymAdminClassTemplatesPage - flujo integrado de clases', () => {
  it('abre en clases reales por fecha y oculta los accesos manuales legacy', async () => {
    renderPage()

    await waitFor(() => expect(classesApi.byDate).toHaveBeenCalled())
    expect(screen.getByText('Detalle de clases (filtrado)')).toBeInTheDocument()
    expect(screen.queryByText('Clases programadas')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /actualizar clases/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /ver clases generadas/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/generar rango pendiente/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/reactivar futuras canceladas/i)).not.toBeInTheDocument()
  })

  it('muestra programacion como pestana interna sin acciones manuales por fila', async () => {
    classTemplatesApi.list.mockResolvedValue([
      {
        id: 5,
        name: 'Serie existente',
        branch: 1,
        teacher: 2,
        class_type: 3,
        discipline: 4,
        weekday: 3,
        start_time: '10:00:00',
        end_time: '11:00:00',
        capacity: 15,
        is_active: true,
        is_trial_eligible: false,
      },
    ])

    await openScheduleTab()
    await userEvent.click((await screen.findAllByRole('button', { name: /abrir acciones/i }))[0])

    expect(screen.getByRole('button', { name: /^editar$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /generar clases/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reactivar futuras canceladas/i })).not.toBeInTheDocument()
  })

  it('desactiva eliminar programacion cuando el backend indica que ya tiene historial', async () => {
    classTemplatesApi.list.mockResolvedValue([
      {
        id: 7,
        name: 'Serie con historial',
        branch: 1,
        teacher: 2,
        class_type: 3,
        discipline: 4,
        weekday: 1,
        start_time: '09:00:00',
        end_time: '10:00:00',
        capacity: 12,
        is_active: true,
        is_trial_eligible: false,
        can_delete: false,
        delete_block_reason: 'La serie tiene historial consolidado.',
      },
    ])

    await openScheduleTab()
    await userEvent.click((await screen.findAllByRole('button', { name: /abrir acciones/i }))[0])

    expect(screen.getByRole('button', { name: /eliminar programacion/i })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: /motivo bloqueo/i }))
    expect(screen.getByText('La serie tiene historial consolidado.')).toBeInTheDocument()
  })
})


describe('GymAdminClassTemplatesPage - formulario de creacion (multi-dia, sin fechas)', () => {
  beforeEach(() => {
    // Un item por catalogo para poder completar los <select required> del form.
    branchesApi.list.mockResolvedValue([{ id: 1, name: 'Sede Centro' }])
    usersApi.list.mockResolvedValue([{ id: 2, first_name: 'Ana', last_name: 'Prof', username: 'ana' }])
    classTypesApi.list.mockResolvedValue([{ id: 3, name: 'Funcional' }])
    disciplinesApi.list.mockResolvedValue([{ id: 4, name: 'Crossfit' }])
  })

  async function fillRequiredFieldsExceptDays() {
    // Los <select> arrancan sin opciones (loadData todavia no resolvio); esperamos a que el
    // catalogo de sucursales llegue antes de intentar seleccionar, si no selectOptions tira
    // "option not found".
    await screen.findByRole('option', { name: 'Sede Centro' })
    await userEvent.selectOptions(screen.getByLabelText(/sucursal/i), '1')
    await userEvent.selectOptions(screen.getByLabelText(/profesor/i), '2')
    await userEvent.selectOptions(screen.getByLabelText(/^tipo$/i), '3')
    await userEvent.selectOptions(screen.getByLabelText(/disciplina/i), '4')
    // Los inputs type="time" son inestables con userEvent.type (steppers por segmento);
    // fireEvent.change es el patron robusto para setear su valor en jsdom.
    fireEvent.change(screen.getByLabelText(/hora inicio/i), { target: { value: '08:00' } })
    fireEvent.change(screen.getByLabelText(/hora termino/i), { target: { value: '09:00' } })
  }

  // Los dias ya no son checkboxes sueltos en el form: viven dentro de MultiSelectDropdown, que
  // los monta en un portal recien al abrirse. Hay que abrir, marcar y cerrar con "Listo".
  async function selectDays(...dayNames) {
    await userEvent.click(screen.getByRole('button', { name: /dias de la semana/i }))
    for (const name of dayNames) {
      await userEvent.click(await screen.findByRole('checkbox', { name }))
    }
    await userEvent.click(screen.getByRole('button', { name: /^listo$/i }))
  }

  it('marcar Lunes/Miercoles/Viernes y enviar llama a create con weekdays=[0,2,4] y sin start_date/end_date/weekday', async () => {
    classTemplatesApi.create.mockResolvedValue({ created: [{ id: 10 }, { id: 11 }, { id: 12 }], skipped: [] })
    await openCreateForm()
    await fillRequiredFieldsExceptDays()
    await selectDays(/lunes/i, /miercoles/i, /viernes/i)

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    await waitFor(() => expect(classTemplatesApi.create).toHaveBeenCalledTimes(1))
    const payload = classTemplatesApi.create.mock.calls[0][0]
    expect(payload.weekdays).toEqual([0, 2, 4])
    expect(payload).not.toHaveProperty('weekday')
    expect(payload).not.toHaveProperty('start_date')
    expect(payload).not.toHaveProperty('end_date')
  })

  it('el trigger resume los dias elegidos de forma legible y las opciones no estan montadas con el panel cerrado', async () => {
    await openCreateForm()

    // Cerrado: ni una opcion en el DOM, solo el placeholder.
    expect(screen.queryByRole('checkbox', { name: /lunes/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /dias de la semana/i })).toHaveTextContent('Elegi uno o mas dias')

    await selectDays(/lunes/i, /miercoles/i, /viernes/i)

    const trigger = screen.getByRole('button', { name: /dias de la semana/i })
    expect(trigger).toHaveTextContent('Lunes, Miercoles y Viernes')
    // Al cerrar, las opciones se desmontan de nuevo.
    expect(screen.queryByRole('checkbox', { name: /lunes/i })).not.toBeInTheDocument()
  })

  it('marcar los 7 dias colapsa el resumen a "Todos los dias"', async () => {
    await openCreateForm()

    await selectDays(/lunes/i, /martes/i, /miercoles/i, /jueves/i, /viernes/i, /sabado/i, /domingo/i)

    expect(screen.getByRole('button', { name: /dias de la semana/i })).toHaveTextContent('Todos los dias')
  })

  it('destildar un dia lo saca de la seleccion y el orden del payload sigue el de la semana', async () => {
    classTemplatesApi.create.mockResolvedValue({ created: [{ id: 30 }, { id: 31 }], skipped: [] })
    await openCreateForm()
    await fillRequiredFieldsExceptDays()

    // Se marca en desorden (Viernes antes que Lunes) y se destilda Miercoles dentro del panel.
    await userEvent.click(screen.getByRole('button', { name: /dias de la semana/i }))
    await userEvent.click(await screen.findByRole('checkbox', { name: /viernes/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /miercoles/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /lunes/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /miercoles/i }))
    await userEvent.click(screen.getByRole('button', { name: /^listo$/i }))

    expect(screen.getByRole('button', { name: /dias de la semana/i })).toHaveTextContent('Lunes y Viernes')

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    await waitFor(() => expect(classTemplatesApi.create).toHaveBeenCalledTimes(1))
    expect(classTemplatesApi.create.mock.calls[0][0].weekdays).toEqual([0, 4])
  })

  it('enviar sin marcar ningun dia no llama al API y muestra el error', async () => {
    await openCreateForm()
    await fillRequiredFieldsExceptDays()

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    expect(await screen.findByText('Elegi al menos un dia.')).toBeInTheDocument()
    expect(classTemplatesApi.create).not.toHaveBeenCalled()
  })

  it('el aviso de creacion usa created.length y avisa de los duplicados salteados', async () => {
    classTemplatesApi.create.mockResolvedValue({
      created: [{ id: 20 }, { id: 21 }],
      skipped: [{ weekday: 4, existing_id: 99 }],
    })
    await openCreateForm()
    await fillRequiredFieldsExceptDays()
    await selectDays(/lunes/i, /miercoles/i, /viernes/i)

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    expect(
      await screen.findByText('Se programaron 2 clases semanales. Las clases se generan automaticamente. 1 ya existian y no se duplicaron.'),
    ).toBeInTheDocument()
  })

  it('si todos los dias ya existian (created vacio) avisa que no se creo nada nuevo', async () => {
    classTemplatesApi.create.mockResolvedValue({
      created: [],
      skipped: [{ weekday: 0, existing_id: 1 }, { weekday: 2, existing_id: 2 }],
    })
    await openCreateForm()
    await fillRequiredFieldsExceptDays()
    await selectDays(/lunes/i, /miercoles/i)

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    expect(
      await screen.findByText('No se programo ninguna clase nueva: los 2 dias elegidos ya tenian una clase.'),
    ).toBeInTheDocument()
  })

  it('en edicion se mantiene el selector singular de dia y el update manda weekday sin fechas', async () => {
    classTemplatesApi.list.mockResolvedValue([
      {
        id: 5,
        name: 'Serie existente',
        branch: 1,
        teacher: 2,
        class_type: 3,
        discipline: 4,
        weekday: 3,
        start_time: '10:00:00',
        end_time: '11:00:00',
        capacity: 15,
        is_active: true,
        is_trial_eligible: false,
      },
    ])
    classTemplatesApi.update.mockResolvedValue({ id: 5 })
    await openScheduleTab()

    // Las acciones de fila viven detras del gear ("Abrir acciones", DataTable.RowActionsDropdown).
    // DataTable duplica la fila en DOM (tabla desktop + tarjeta mobile) porque los tests corren
    // sin CSS (vitest.config.js: css:false) y las utilidades "hidden"/"lg:block" no aplican; con
    // el menu cerrado eso no genera ambiguedad porque los botones de accion no se montan hasta
    // abrir, pero el propio boton "Abrir acciones" SI esta duplicado. Abrimos el primero.
    const [menuTrigger] = await screen.findAllByRole('button', { name: /abrir acciones/i })
    await userEvent.click(menuTrigger)
    await userEvent.click(await screen.findByRole('button', { name: /^editar$/i }))
    await screen.findByLabelText(/nombre visible/i)

    // En edicion el selector es singular ("Dia semana"), no los checkboxes multi-dia.
    expect(screen.getByLabelText(/^dia semana$/i)).toBeInTheDocument()
    expect(screen.queryByText(/dias de la semana/i)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /guardar cambios/i }))

    await waitFor(() => expect(classTemplatesApi.update).toHaveBeenCalledTimes(1))
    const [id, payload] = classTemplatesApi.update.mock.calls[0]
    expect(id).toBe(5)
    expect(payload.weekday).toBe(3)
    expect(payload.apply_to_future_instances).toBe(true)
    expect(payload).not.toHaveProperty('weekdays')
    expect(payload).not.toHaveProperty('start_date')
    expect(payload).not.toHaveProperty('end_date')
  })

  it('al editar enfoca el formulario y Cancelar edicion limpia el estado', async () => {
    classTemplatesApi.list.mockResolvedValue([
      {
        id: 5,
        name: 'Serie existente',
        branch: 1,
        teacher: 2,
        class_type: 3,
        discipline: 4,
        weekday: 3,
        start_time: '10:00:00',
        end_time: '11:00:00',
        capacity: 15,
        is_active: true,
        is_trial_eligible: false,
      },
    ])
    await openScheduleTab()

    const [menuTrigger] = await screen.findAllByRole('button', { name: /abrir acciones/i })
    await userEvent.click(menuTrigger)
    await userEvent.click(await screen.findByRole('button', { name: /^editar$/i }))

    expect(await screen.findByText(/editando clase #5/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/nombre visible/i)).toHaveFocus())

    await userEvent.click(screen.getByRole('button', { name: /cancelar edicion/i }))

    expect(screen.queryByText(/editando clase #5/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/nombre visible/i)).not.toBeInTheDocument()
  })
})

describe('GymAdminClassTemplatesPage - clase con suplente (P4 #A)', () => {
  beforeEach(() => {
    branchesApi.list.mockResolvedValue([{ id: 1, name: 'Sede Centro' }])
    usersApi.list.mockResolvedValue([{ id: 2, first_name: 'Ana', last_name: 'Prof', username: 'ana' }])
    classTypesApi.list.mockResolvedValue([{ id: 3, name: 'Funcional' }])
    disciplinesApi.list.mockResolvedValue([{ id: 4, name: 'Crossfit' }])
  })

  it('el input de nombre del suplente solo aparece cuando el check esta marcado', async () => {
    await openCreateForm()

    // Cerrado por defecto: el input no esta montado.
    expect(screen.queryByLabelText(/nombre del suplente/i)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox', { name: /clase con suplente/i }))

    expect(screen.getByLabelText(/nombre del suplente/i)).toBeInTheDocument()

    // Al destildar, el input se desmonta de nuevo (y el nombre se limpia, ver siguiente test).
    await userEvent.click(screen.getByRole('checkbox', { name: /clase con suplente/i }))

    expect(screen.queryByLabelText(/nombre del suplente/i)).not.toBeInTheDocument()
  })

  it('al destildar el check se limpia el nombre cargado (no manda un suplente huerfano)', async () => {
    classTemplatesApi.create.mockResolvedValue({ created: [{ id: 40 }], skipped: [] })
    await openCreateForm()

    await userEvent.click(screen.getByRole('checkbox', { name: /clase con suplente/i }))
    await userEvent.type(screen.getByLabelText(/nombre del suplente/i), 'Marcela Rios')
    await userEvent.click(screen.getByRole('checkbox', { name: /clase con suplente/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /clase con suplente/i }))

    expect(screen.getByLabelText(/nombre del suplente/i)).toHaveValue('')
  })
})
