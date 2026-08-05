import { render, screen, waitFor } from '@testing-library/react'
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
