import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La página carga estos módulos al montar (loadData) y usa advanceClassWindowsApi
// para el botón "Actualizar clases" (robot de la ventana rodante disparado a mano).
vi.mock('../api/client', () => ({
  advanceClassWindowsApi: { run: vi.fn() },
  branchesApi: { list: vi.fn() },
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
  classTemplatesApi,
  classTypesApi,
  disciplinesApi,
  usersApi,
} from '../api/client'
import GymAdminClassTemplatesPage from './GymAdminClassTemplatesPage'

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
  classTemplatesApi.list.mockResolvedValue([])
  branchesApi.list.mockResolvedValue([])
  usersApi.list.mockResolvedValue([])
  classTypesApi.list.mockResolvedValue([])
  disciplinesApi.list.mockResolvedValue([])
  // DataTable consulta matchMedia al montar; jsdom no lo implementa. Mismo patrón
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
})

describe('GymAdminClassTemplatesPage — botón "Actualizar clases" (robot de ventana rodante)', () => {
  it('gym_admin: el botón aparece en la pantalla de series recurrentes', async () => {
    renderPage()
    expect(await screen.findByRole('button', { name: /actualizar clases/i })).toBeInTheDocument()
  })

  it('manager: el botón NO aparece (el backend solo autoriza a gym_admin)', async () => {
    mockRole = 'manager'
    renderPage()
    // Esperamos a que la carga inicial termine para no confundir "aún no montó" con "oculto".
    await waitFor(() => expect(classTemplatesApi.list).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /actualizar clases/i })).not.toBeInTheDocument()
  })

  it('click abre la confirmación y NO postea hasta confirmar', async () => {
    renderPage()
    const trigger = await screen.findByRole('button', { name: /actualizar clases/i })
    await userEvent.click(trigger)

    expect(
      await screen.findByText(/esto va a generar las clases próximas y eliminar las clases vacías vencidas/i),
    ).toBeInTheDocument()
    expect(advanceClassWindowsApi.run).not.toHaveBeenCalled()
  })

  it('confirmar postea y muestra el resultado con los counts (sin avisos)', async () => {
    advanceClassWindowsApi.run.mockResolvedValue({ instances_created: 12, pruned_count: 3, errors: [] })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /actualizar clases/i }))
    await userEvent.click(await screen.findByRole('button', { name: /sí, actualizar/i }))

    await waitFor(() => expect(advanceClassWindowsApi.run).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Se generaron 12 clases, se eliminaron 3 clases vacías.')).toBeInTheDocument()
  })

  it('confirmar con errores no vacíos agrega ", con N avisos" al mensaje', async () => {
    advanceClassWindowsApi.run.mockResolvedValue({
      instances_created: 5,
      pruned_count: 0,
      errors: ['no se pudo generar la clase X', 'no se pudo podar la clase Y'],
    })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /actualizar clases/i }))
    await userEvent.click(await screen.findByRole('button', { name: /sí, actualizar/i }))

    expect(
      await screen.findByText('Se generaron 5 clases, se eliminaron 0 clases vacías, con 2 avisos.'),
    ).toBeInTheDocument()
  })

  it('error del POST (403) muestra el mensaje de error del backend Y cierra el diálogo de confirmación', async () => {
    advanceClassWindowsApi.run.mockRejectedValue({
      response: { status: 403, data: { detail: 'Solo el administrador del gimnasio puede ejecutar la actualización de clases.' } },
    })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /actualizar clases/i }))
    await userEvent.click(await screen.findByRole('button', { name: /sí, actualizar/i }))

    expect(
      await screen.findByText('Solo el administrador del gimnasio puede ejecutar la actualización de clases.'),
    ).toBeInTheDocument()
    // Regresión: el ConfirmDialog es un portal full-viewport con backdrop opaco que tapa el
    // banner de error de la página. Si no se cerrara en el path de error, el admin vería el
    // diálogo ahí parado sin feedback visible (el botón vuelve de "Procesando..." a "Sí,
    // actualizar") y podría creer que no pasó nada y reintentar. El assert correcto es que el
    // modal se cerró, no que el error "se vea" (RTL no modela oclusión de layout).
    expect(
      screen.queryByText(/esto va a generar las clases próximas y eliminar las clases vacías vencidas/i),
    ).not.toBeInTheDocument()
  })

  it('mientras la petición está en curso el botón queda deshabilitado y un segundo click no dispara un segundo POST', async () => {
    let resolveRun
    advanceClassWindowsApi.run.mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve
      }),
    )
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /actualizar clases/i }))
    await userEvent.click(await screen.findByRole('button', { name: /sí, actualizar/i }))

    // El botón de la cabecera pasa a estado "Actualizando..." y queda disabled.
    const pendingTrigger = await screen.findByRole('button', { name: /actualizando/i })
    expect(pendingTrigger).toBeDisabled()

    // Un segundo click sobre el botón disabled (userEvent respeta el atributo y no dispara el
    // handler) no debe sumar una segunda llamada mientras la primera sigue pendiente.
    await userEvent.click(pendingTrigger)
    expect(advanceClassWindowsApi.run).toHaveBeenCalledTimes(1)

    resolveRun({ instances_created: 1, pruned_count: 0, errors: [] })
    await waitFor(() => expect(advanceClassWindowsApi.run).toHaveBeenCalledTimes(1))
  })
})

describe('GymAdminClassTemplatesPage — formulario de creacion (multi-dia, sin fechas)', () => {
  beforeEach(() => {
    // Un item por catalogo para poder completar los <select required> del form.
    branchesApi.list.mockResolvedValue([{ id: 1, name: 'Sede Centro' }])
    usersApi.list.mockResolvedValue([{ id: 2, first_name: 'Ana', last_name: 'Prof', username: 'ana' }])
    classTypesApi.list.mockResolvedValue([{ id: 3, name: 'Funcional' }])
    disciplinesApi.list.mockResolvedValue([{ id: 4, name: 'Crossfit' }])
  })

  async function fillRequiredFieldsExceptDays() {
    // Los <select> arrancan sin opciones (loadData todavia no resolvió); esperamos a que el
    // catalogo de sucursales llegue antes de intentar seleccionar, si no selectOptions tira
    // "option not found".
    await screen.findByRole('option', { name: 'Sede Centro' })
    await userEvent.selectOptions(screen.getByLabelText(/sucursal/i), '1')
    await userEvent.selectOptions(screen.getByLabelText(/profesor/i), '2')
    await userEvent.selectOptions(screen.getByLabelText(/^tipo$/i), '3')
    await userEvent.selectOptions(screen.getByLabelText(/disciplina/i), '4')
    // Los inputs type="time" son inestables con userEvent.type (steppers por segmento);
    // fireEvent.change es el patrón robusto para setear su valor en jsdom.
    fireEvent.change(screen.getByLabelText(/hora inicio/i), { target: { value: '08:00' } })
    fireEvent.change(screen.getByLabelText(/hora termino/i), { target: { value: '09:00' } })
  }

  it('marcar Lunes/Miercoles/Viernes y enviar llama a create con weekdays=[0,2,4] y sin start_date/end_date/weekday', async () => {
    classTemplatesApi.create.mockResolvedValue({ created: [{ id: 10 }, { id: 11 }, { id: 12 }], skipped: [] })
    renderPage()

    await screen.findByRole('heading', { name: /nueva serie recurrente/i })
    await fillRequiredFieldsExceptDays()
    await userEvent.click(screen.getByRole('checkbox', { name: /lunes/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /miercoles/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /viernes/i }))

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    await waitFor(() => expect(classTemplatesApi.create).toHaveBeenCalledTimes(1))
    const payload = classTemplatesApi.create.mock.calls[0][0]
    expect(payload.weekdays).toEqual([0, 2, 4])
    expect(payload).not.toHaveProperty('weekday')
    expect(payload).not.toHaveProperty('start_date')
    expect(payload).not.toHaveProperty('end_date')
  })

  it('enviar sin marcar ningun dia no llama al API y muestra el error', async () => {
    renderPage()

    await screen.findByRole('heading', { name: /nueva serie recurrente/i })
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
    renderPage()

    await screen.findByRole('heading', { name: /nueva serie recurrente/i })
    await fillRequiredFieldsExceptDays()
    await userEvent.click(screen.getByRole('checkbox', { name: /lunes/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /miercoles/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /viernes/i }))

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    expect(
      await screen.findByText('Se crearon 2 series. Las clases se generan automaticamente. 1 ya existian y no se duplicaron.'),
    ).toBeInTheDocument()
  })

  it('si todos los dias ya existian (created vacio) avisa que no se creo nada nuevo', async () => {
    classTemplatesApi.create.mockResolvedValue({
      created: [],
      skipped: [{ weekday: 0, existing_id: 1 }, { weekday: 2, existing_id: 2 }],
    })
    renderPage()

    await screen.findByRole('heading', { name: /nueva serie recurrente/i })
    await fillRequiredFieldsExceptDays()
    await userEvent.click(screen.getByRole('checkbox', { name: /lunes/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /miercoles/i }))

    await userEvent.click(screen.getByRole('button', { name: /guardar y generar clases/i }))

    expect(
      await screen.findByText('No se creo ninguna serie nueva: los 2 dias elegidos ya tenian una serie.'),
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
    renderPage()

    // Las acciones de fila viven detras del gear ("Abrir acciones", DataTable.RowActionsDropdown).
    // DataTable duplica la fila en DOM (tabla desktop + tarjeta mobile) porque los tests corren
    // sin CSS (vitest.config.js: css:false) y las utilidades "hidden"/"lg:block" no aplican; con
    // el menu cerrado eso no genera ambiguedad porque los botones de accion no se montan hasta
    // abrir, pero el propio boton "Abrir acciones" SI está duplicado. Abrimos el primero.
    const [menuTrigger] = await screen.findAllByRole('button', { name: /abrir acciones/i })
    await userEvent.click(menuTrigger)
    await userEvent.click(await screen.findByRole('button', { name: /^editar$/i }))
    await screen.findByRole('heading', { name: /editar serie/i })

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
})
