import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La página llama a estos módulos al montar (loadData). Los mockeamos para que
// resuelvan vacío y el árbol se renderice sin red real.
vi.mock('../api/client', () => ({
  classesApi: { list: vi.fn() },
  enrollmentsApi: { my: vi.fn(), create: vi.fn(), cancel: vi.fn() },
  recurringEnrollmentsApi: { my: vi.fn(), update: vi.fn() },
  classTemplatesApi: { recurringEnroll: vi.fn() },
  getMyMemberships: vi.fn(),
}))

import { classesApi, classTemplatesApi, enrollmentsApi, recurringEnrollmentsApi, getMyMemberships } from '../api/client'
import StudentClassesPage from './StudentClassesPage'

function renderPage(mode = 'available') {
  return render(
    <MemoryRouter>
      <StudentClassesPage mode={mode} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.list.mockResolvedValue([])
  enrollmentsApi.my.mockResolvedValue([])
  recurringEnrollmentsApi.my.mockResolvedValue([])
  getMyMemberships.mockResolvedValue([])
  // jsdom no implementa matchMedia. Lo hacemos "query-aware": escritorio (min-width)
  // → true, para que FilterPanel abra y muestre los chips; DataTable (max-width)
  // → false, para que renderice la tabla de escritorio.
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

describe('StudentClassesPage — rango por defecto (#18)', () => {
  it('al montar, la lista de clases disponibles arranca en el rango de la semana actual', async () => {
    renderPage('available')
    // Deja que el fetch inicial se resuelva (evita warnings de act).
    await waitFor(() => expect(classesApi.list).toHaveBeenCalled())

    const semana = screen.getByRole('button', { name: 'Semana' })
    const hoy = screen.getByRole('button', { name: 'Hoy' })
    // "Semana" activo por defecto (no arranca mostrando todo/2 años).
    expect(semana).toHaveClass('bg-brand-blue/20')
    expect(hoy).not.toHaveClass('bg-brand-blue/20')
  })
})

const DAY = 24 * 60 * 60 * 1000
const isoIn = (ms) => new Date(Date.now() + ms).toISOString()

// Una clase reservable dentro de la semana actual (para que pase el filtro por
// defecto), sin reserva activa y con plan con saldo → botón "Reservar" habilitado.
const FUTURE_ISO = new Date(Date.now() + 2 * DAY).toISOString()

function seedReservableClass() {
  classesApi.list
    .mockResolvedValueOnce([
      {
        id: 101,
        name: 'Yoga',
        status: 'scheduled',
        start_datetime: FUTURE_ISO,
        end_datetime: FUTURE_ISO,
        capacity: 10,
        enrollments_count: 0,
        branch_name: 'Sede',
        teacher_name: 'Prof',
        discipline_name: 'Yoga',
        class_template: null,
      },
    ])
    .mockResolvedValueOnce([])
  enrollmentsApi.my.mockResolvedValue([])
  recurringEnrollmentsApi.my.mockResolvedValue([])
  // Una sola membresía usable con saldo finito → el payload de creación NO debe
  // llevar student_plan_id (el backend lo resuelve solo).
  getMyMemberships.mockResolvedValue([
    { id: 1, plan_name: 'Plan Básico', remaining_classes: 10, unlimited_classes: false, validity_status: 'active' },
  ])
  enrollmentsApi.create.mockResolvedValue({})
}

describe('StudentClassesPage — confirmar antes de reservar (#24)', () => {
  beforeEach(() => {
    // Vista de tarjetas (max-width): el botón "Reservar" (mobilePrimary) se
    // renderiza directo, sin el dropdown de acciones de la tabla de escritorio.
    window.matchMedia = (query) => ({
      matches: query.includes('max-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  it('reservar dispara un diálogo de confirmación; confirmar procede', async () => {
    seedReservableClass()
    renderPage('available')
    const user = userEvent.setup()

    const reservar = await screen.findByRole('button', { name: 'Reservar' })
    await user.click(reservar)

    // Aparece el diálogo "¿Seguro?" y todavía NO se reservó.
    expect(await screen.findByText(/¿seguro/i)).toBeInTheDocument()
    expect(enrollmentsApi.create).not.toHaveBeenCalled()

    // Confirmar dentro del diálogo → procede la reserva.
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Reservar' }))

    await waitFor(() =>
      expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 101, status: 'active' }),
    )
  })

  it('cancelar en el diálogo aborta la reserva', async () => {
    seedReservableClass()
    renderPage('available')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Reservar' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(enrollmentsApi.create).not.toHaveBeenCalled()
  })
})

describe('StudentClassesPage — "Limpiar" quita TODOS los filtros incluido el rango (#18 fix)', () => {
  beforeEach(() => {
    // Vista escritorio: FilterPanel abierto (min-width→true) + tabla (max-width→false).
    window.matchMedia = (query) => ({
      matches: query.includes('min-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  it('una clase FUERA de la semana aparece tras "Limpiar" y el chip Semana se desactiva', async () => {
    // Clase a 30 días: fuera de la ventana "semana" (default), así que arranca oculta.
    classesApi.list
      .mockResolvedValueOnce([
        {
          id: 201,
          name: 'ClaseLejana',
          status: 'scheduled',
          start_datetime: isoIn(30 * DAY),
          end_datetime: isoIn(30 * DAY + 60 * 60 * 1000),
          capacity: 10,
          enrollments_count: 0,
          class_template: null,
        },
      ])
      .mockResolvedValueOnce([])
    getMyMemberships.mockResolvedValue([
      { id: 1, plan_name: 'Plan Básico', remaining_classes: 10, unlimited_classes: false, validity_status: 'active' },
    ])

    renderPage('available')
    const user = userEvent.setup()
    await waitFor(() => expect(classesApi.list).toHaveBeenCalled())

    // Por defecto (semana) la clase a 30 días NO se muestra.
    expect(screen.queryAllByText('ClaseLejana')).toHaveLength(0)

    // "Limpiar" debe estar disponible (hay un filtro activo: la semana) y quitar
    // TODOS los filtros, incluido el rango → la clase aparece.
    await user.click(screen.getByRole('button', { name: /limpiar/i }))
    expect((await screen.findAllByText('ClaseLejana')).length).toBeGreaterThan(0)

    // Y el chip "Semana" queda inactivo tras limpiar.
    expect(screen.getByRole('button', { name: 'Semana' })).not.toHaveClass('bg-brand-blue/20')
  })
})

// #9 T4 — imputación de consumo por elección del alumno: saldo desde
// getMyMemberships (no más getMyPlan) + selector de plan cuando hay 2+ vigentes.
describe('StudentClassesPage — saldo desde getMyMemberships y selector de plan (#9 T4)', () => {
  beforeEach(() => {
    // Vista de tarjetas: igual que en #24, así el botón "Reservar" sale del
    // mobilePrimary con nombre accesible simple ("Reservar").
    window.matchMedia = (query) => ({
      matches: query.includes('max-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  function seedClass(id, name = 'Clase') {
    classesApi.list
      .mockResolvedValueOnce([
        {
          id,
          name,
          status: 'scheduled',
          start_datetime: FUTURE_ISO,
          end_datetime: FUTURE_ISO,
          capacity: 10,
          enrollments_count: 0,
          branch_name: 'Sede',
          teacher_name: 'Prof',
          discipline_name: 'Yoga',
          class_template: null,
        },
      ])
      .mockResolvedValueOnce([])
    enrollmentsApi.my.mockResolvedValue([])
    recurringEnrollmentsApi.my.mockResolvedValue([])
    enrollmentsApi.create.mockResolvedValue({})
  }

  it('con una membresía ilimitada (remaining_classes null), el botón Reservar está habilitado y el chip dice "Clases ilimitadas" (el bug viejo lo bloqueaba)', async () => {
    seedClass(301, 'Crossfit')
    getMyMemberships.mockResolvedValue([
      { id: 9, plan_name: 'Plan Ilimitado', remaining_classes: null, unlimited_classes: true, validity_status: 'active' },
    ])

    renderPage('available')
    const user = userEvent.setup()

    expect(await screen.findByText('Clases ilimitadas')).toBeInTheDocument()
    const reservar = await screen.findByRole('button', { name: 'Reservar' })
    expect(reservar).toBeEnabled()

    // Confirmar la reserva completa: con una sola membresía usable, el payload
    // NO lleva student_plan_id (lo resuelve el backend).
    await user.click(reservar)
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Reservar' }))

    await waitFor(() =>
      expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 301, status: 'active' }),
    )
  })

  it('con 2+ membresías usables, el diálogo exige elegir un plan antes de confirmar y lo manda como student_plan_id', async () => {
    seedClass(401, 'Pilates')
    getMyMemberships.mockResolvedValue([
      { id: 11, plan_name: 'Plan A', remaining_classes: 3, unlimited_classes: false, validity_status: 'active' },
      { id: 12, plan_name: 'Plan B', remaining_classes: null, unlimited_classes: true, validity_status: 'active' },
    ])

    renderPage('available')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Reservar' }))
    const dialog = await screen.findByRole('dialog')

    const confirmButton = within(dialog).getByRole('button', { name: 'Reservar' })
    // Sin selección, el diálogo no deja confirmar.
    expect(confirmButton).toBeDisabled()
    expect(enrollmentsApi.create).not.toHaveBeenCalled()

    const select = within(dialog).getByRole('combobox')
    expect(within(select).getByText('Plan A — quedan 3')).toBeInTheDocument()
    expect(within(select).getByText('Plan B — clases ilimitadas')).toBeInTheDocument()

    await user.selectOptions(select, '12')
    expect(confirmButton).toBeEnabled()

    await user.click(confirmButton)

    await waitFor(() =>
      expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 401, status: 'active', student_plan_id: 12 }),
    )
  })
})

// Ronda de fix 1 (revisión T4) — hallazgo Important: rebook y bulk decidían con el
// mismo `requiresPlanChoice` que la reserva individual, pero no tenían ninguna
// aserción end-to-end propia de que (a) abren el selector con 2+ usables y
// (b) mandan el student_plan_id elegido en el/los payloads.
describe('StudentClassesPage — rebook con selector de plan (#9 T4 fix)', () => {
  beforeEach(() => {
    // Vista escritorio (min-width→true): hace falta que el FilterPanel arranque
    // abierto para poder cambiar el filtro "Estado" a "Canceladas". NOTA: DataTable
    // renderiza SIEMPRE ambos bloques (tabla desktop + grid de tarjetas) en el DOM
    // de jsdom — la alternancia real es solo CSS (`hidden lg:block` / `lg:hidden`),
    // que jsdom no aplica — así que cualquier texto/botón que se repita entre
    // ambos bloques sale ambiguo. Por eso este test usa "Ver detalle" (que solo
    // existe una vez, en el bloque de tarjetas) en vez de texto de la fila o el
    // menú "Abrir acciones" (duplicado: uno por bloque).
    window.matchMedia = (query) => ({
      matches: query.includes('min-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  it('con 2+ membresías usables, el rebook desde "Mis reservas" exige elegir un plan y lo manda como student_plan_id', async () => {
    classesApi.list.mockResolvedValue([])
    enrollmentsApi.my.mockResolvedValue([
      {
        id: 501,
        gym_class: 601,
        gym_class_name: 'Spinning',
        status: 'cancelled',
        class_status: 'scheduled',
        class_start: FUTURE_ISO,
        class_end: FUTURE_ISO,
        class_branch_name: 'Sede',
        class_teacher_name: 'Prof',
        class_discipline_name: 'Ciclismo',
        class_type_name: 'Grupal',
        reservation_kind: 'single',
        class_template_id: null,
        recurring_enrollment: null,
        can_cancel: true,
      },
    ])
    recurringEnrollmentsApi.my.mockResolvedValue([])
    getMyMemberships.mockResolvedValue([
      { id: 11, plan_name: 'Plan A', remaining_classes: 3, unlimited_classes: false, validity_status: 'active' },
      { id: 12, plan_name: 'Plan B', remaining_classes: null, unlimited_classes: true, validity_status: 'active' },
    ])
    enrollmentsApi.create.mockResolvedValue({})

    renderPage('reservations')
    const user = userEvent.setup()
    await waitFor(() => expect(enrollmentsApi.my).toHaveBeenCalled())

    // La reserva está cancelada; el filtro default ("Activas") la esconde.
    // Cambiar "Estado" → "Canceladas" para verla.
    await user.click(screen.getByRole('button', { name: /^Estado:/i }))
    await user.click(await screen.findByRole('button', { name: 'Canceladas' }))

    // "Ver detalle" es único por fila (solo existe en el bloque de tarjetas); al
    // abrir el modal de detalle se pinta el botón "Reservar" (rebook) sin envolver
    // en el menú "Abrir acciones", así que no hay ambigüedad de queries.
    await user.click(await screen.findByRole('button', { name: 'Ver detalle' }))
    await user.click(await screen.findByRole('button', { name: 'Reservar' }))

    const dialog = await screen.findByRole('dialog')
    const confirmButton = within(dialog).getByRole('button', { name: 'Reservar' })
    expect(confirmButton).toBeDisabled()
    expect(enrollmentsApi.create).not.toHaveBeenCalled()

    const select = within(dialog).getByRole('combobox')
    await user.selectOptions(select, '11')
    expect(confirmButton).toBeEnabled()

    await user.click(confirmButton)

    await waitFor(() =>
      expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 601, status: 'active', student_plan_id: 11 }),
    )
  })
})

describe('StudentClassesPage — bulk con selector de plan (#9 T4 fix)', () => {
  beforeEach(() => {
    // Vista de tarjetas: los checkboxes de selección de fila salen directos
    // (aria-label "Seleccionar fila"), sin depender del checkbox "seleccionar
    // todo" de la cabecera de la tabla de escritorio.
    window.matchMedia = (query) => ({
      matches: query.includes('max-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  it('con 2+ membresías usables, el bulk abre el selector UNA vez y aplica el mismo student_plan_id a todo el lote', async () => {
    classesApi.list
      .mockResolvedValueOnce([
        {
          id: 701,
          name: 'Clase A',
          status: 'scheduled',
          start_datetime: FUTURE_ISO,
          end_datetime: FUTURE_ISO,
          capacity: 10,
          enrollments_count: 0,
          branch_name: 'Sede',
          teacher_name: 'Prof',
          discipline_name: 'Yoga',
          class_template: null,
        },
        {
          id: 702,
          name: 'Clase B',
          status: 'scheduled',
          start_datetime: FUTURE_ISO,
          end_datetime: FUTURE_ISO,
          capacity: 10,
          enrollments_count: 0,
          branch_name: 'Sede',
          teacher_name: 'Prof',
          discipline_name: 'Yoga',
          class_template: null,
        },
      ])
      .mockResolvedValueOnce([])
    enrollmentsApi.my.mockResolvedValue([])
    recurringEnrollmentsApi.my.mockResolvedValue([])
    getMyMemberships.mockResolvedValue([
      { id: 21, plan_name: 'Plan A', remaining_classes: 5, unlimited_classes: false, validity_status: 'active' },
      { id: 22, plan_name: 'Plan B', remaining_classes: null, unlimited_classes: true, validity_status: 'active' },
    ])
    enrollmentsApi.create.mockResolvedValue({})

    renderPage('available')
    const user = userEvent.setup()

    const checkboxes = await screen.findAllByRole('checkbox', { name: 'Seleccionar fila' })
    expect(checkboxes).toHaveLength(2)
    await user.click(checkboxes[0])
    await user.click(checkboxes[1])

    await user.click(screen.getByRole('button', { name: 'Reservar seleccionadas' }))

    const dialog = await screen.findByRole('dialog')
    const confirmButton = within(dialog).getByRole('button', { name: 'Reservar seleccionadas' })
    // Sin selección, no se puede confirmar y no corrió ningún create todavía.
    expect(confirmButton).toBeDisabled()
    expect(enrollmentsApi.create).not.toHaveBeenCalled()

    const select = within(dialog).getByRole('combobox')
    await user.selectOptions(select, '22')
    expect(confirmButton).toBeEnabled()

    await user.click(confirmButton)

    // El selector se abrió UNA vez y el mismo plan se aplicó a TODO el lote.
    await waitFor(() => expect(enrollmentsApi.create).toHaveBeenCalledTimes(2))
    expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 701, status: 'active', student_plan_id: 22 })
    expect(enrollmentsApi.create).toHaveBeenCalledWith({ gym_class: 702, status: 'active', student_plan_id: 22 })
  })
})

// R1b — el backend ahora acepta/exige student_plan_id en la suscripción a una serie
// recurrente (recurring-enroll). Reusa el MISMO selector/diálogo que reserva
// individual/rebook/bulk (#9 T4): 1 plan usable → sin selector; 2+ → selector
// obligatorio antes de disparar el POST. La reactivación de una serie pausada
// (PATCH is_active) sigue sin selector ni student_plan_id: el backend lo ignora ahí.
describe('StudentClassesPage — suscripción a serie recurrente con selector de plan (R1b)', () => {
  beforeEach(() => {
    // Vista escritorio: la fila de "Clases disponibles" expone el botón de
    // recurrencia detrás de "Abrir acciones" (RowActionsDropdown); en modo
    // 'available' el mobilePrimary siempre define un botón (Reservar/Cancelar),
    // así que la tarjeta móvil NO pinta su propio dropdown y no hay ambigüedad.
    window.matchMedia = (query) => ({
      matches: query.includes('min-width'),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  })

  function seedRecurringClass() {
    classesApi.list
      .mockResolvedValueOnce([
        {
          id: 801,
          name: 'Yoga serie',
          status: 'scheduled',
          start_datetime: FUTURE_ISO,
          end_datetime: FUTURE_ISO,
          capacity: 10,
          enrollments_count: 0,
          branch_name: 'Sede',
          teacher_name: 'Prof',
          discipline_name: 'Yoga',
          class_template: 55,
          class_template_name: 'Yoga Lunes',
        },
      ])
      .mockResolvedValueOnce([])
    enrollmentsApi.my.mockResolvedValue([])
    recurringEnrollmentsApi.my.mockResolvedValue([])
    classTemplatesApi.recurringEnroll.mockResolvedValue({})
  }

  it('con una membresía usable, inscribirse a la serie manda el POST sin student_plan_id y sin selector', async () => {
    seedRecurringClass()
    getMyMemberships.mockResolvedValue([
      { id: 1, plan_name: 'Plan Básico', remaining_classes: 10, unlimited_classes: false, validity_status: 'active' },
    ])

    renderPage('available')
    const user = userEvent.setup()

    await user.click((await screen.findAllByRole('button', { name: 'Abrir acciones' }))[0])
    await user.click(await screen.findByRole('button', { name: 'Inscribirme a esta serie semanal' }))

    // Con una sola membresía usable no hace falta elegir: no aparece diálogo.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await waitFor(() =>
      expect(classTemplatesApi.recurringEnroll).toHaveBeenCalledWith(55, {
        start_date: FUTURE_ISO.slice(0, 10),
        recurrence_type: 'weekly',
      }),
    )
  })

  it('con 2+ membresías usables, el diálogo exige elegir un plan antes de suscribir y lo manda como student_plan_id', async () => {
    seedRecurringClass()
    getMyMemberships.mockResolvedValue([
      { id: 11, plan_name: 'Plan A', remaining_classes: 3, unlimited_classes: false, validity_status: 'active' },
      { id: 12, plan_name: 'Plan B', remaining_classes: null, unlimited_classes: true, validity_status: 'active' },
    ])

    renderPage('available')
    const user = userEvent.setup()

    await user.click((await screen.findAllByRole('button', { name: 'Abrir acciones' }))[0])
    await user.click(await screen.findByRole('button', { name: 'Inscribirme a esta serie semanal' }))

    const dialog = await screen.findByRole('dialog')
    const confirmButton = within(dialog).getByRole('button', { name: 'Inscribirme' })

    // Sin elegir plan, el diálogo no deja confirmar y el POST no se dispara.
    expect(confirmButton).toBeDisabled()
    expect(classTemplatesApi.recurringEnroll).not.toHaveBeenCalled()

    const select = within(dialog).getByRole('combobox')
    expect(within(select).getByText('Plan A — quedan 3')).toBeInTheDocument()
    expect(within(select).getByText('Plan B — clases ilimitadas')).toBeInTheDocument()

    await user.selectOptions(select, '12')
    expect(confirmButton).toBeEnabled()

    await user.click(confirmButton)

    await waitFor(() =>
      expect(classTemplatesApi.recurringEnroll).toHaveBeenCalledWith(55, {
        start_date: FUTURE_ISO.slice(0, 10),
        recurrence_type: 'weekly',
        student_plan_id: 12,
      }),
    )
  })

  it('reactivar una serie pausada NO muestra selector ni manda student_plan_id aunque haya 2+ membresías usables', async () => {
    classesApi.list
      .mockResolvedValueOnce([
        {
          id: 802,
          name: 'Yoga serie pausada',
          status: 'scheduled',
          start_datetime: FUTURE_ISO,
          end_datetime: FUTURE_ISO,
          capacity: 10,
          enrollments_count: 0,
          branch_name: 'Sede',
          teacher_name: 'Prof',
          discipline_name: 'Yoga',
          class_template: 66,
          class_template_name: 'Yoga Martes',
        },
      ])
      .mockResolvedValueOnce([])
    enrollmentsApi.my.mockResolvedValue([])
    recurringEnrollmentsApi.my.mockResolvedValue([
      { id: 900, class_template: 66, is_active: false, can_manage_now: true },
    ])
    recurringEnrollmentsApi.update.mockResolvedValue({})
    getMyMemberships.mockResolvedValue([
      { id: 11, plan_name: 'Plan A', remaining_classes: 3, unlimited_classes: false, validity_status: 'active' },
      { id: 12, plan_name: 'Plan B', remaining_classes: null, unlimited_classes: true, validity_status: 'active' },
    ])

    renderPage('available')
    const user = userEvent.setup()

    await user.click((await screen.findAllByRole('button', { name: 'Abrir acciones' }))[0])
    await user.click(await screen.findByRole('button', { name: 'Reactivar recurrencia semanal' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(recurringEnrollmentsApi.update).toHaveBeenCalledWith(900, { is_active: true }))
    expect(classTemplatesApi.recurringEnroll).not.toHaveBeenCalled()
  })

  it('si el backend responde 400 (plan_choice_required) al suscribir, muestra el detail real del backend', async () => {
    seedRecurringClass()
    getMyMemberships.mockResolvedValue([
      { id: 1, plan_name: 'Plan Básico', remaining_classes: 10, unlimited_classes: false, validity_status: 'active' },
    ])
    classTemplatesApi.recurringEnroll.mockRejectedValue({
      response: { data: { detail: 'Tienes más de un plan vigente. Elige con cuál reservar.' } },
    })

    renderPage('available')
    const user = userEvent.setup()

    await user.click((await screen.findAllByRole('button', { name: 'Abrir acciones' }))[0])
    await user.click(await screen.findByRole('button', { name: 'Inscribirme a esta serie semanal' }))

    expect(await screen.findByText('Tienes más de un plan vigente. Elige con cuál reservar.')).toBeInTheDocument()
  })
})
