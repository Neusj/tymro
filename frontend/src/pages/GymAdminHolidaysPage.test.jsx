import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  branchesApi: { list: vi.fn() },
  holidaysApi: { list: vi.fn(), update: vi.fn(), create: vi.fn(), remove: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin' } }),
}))

import { branchesApi, holidaysApi } from '../api/client'
import GymAdminHolidaysPage from './GymAdminHolidaysPage'

let originalScrollIntoView
let scrollIntoViewMock

function renderPage() {
  return render(
    <MemoryRouter>
      <GymAdminHolidaysPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  originalScrollIntoView = Element.prototype.scrollIntoView
  scrollIntoViewMock = vi.fn()
  Element.prototype.scrollIntoView = scrollIntoViewMock
  window.matchMedia = (query) => ({
    matches: query.includes('min-width'),
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
  branchesApi.list.mockResolvedValue([{ id: 1, name: 'Sede Centro' }])
  holidaysApi.list.mockResolvedValue([
    {
      id: 7,
      date: '2026-09-18',
      name: 'Fiestas Patrias',
      scope: 'organization',
      source_type: 'manual',
      branch: null,
      branch_name: '',
      is_active: true,
    },
  ])
})

afterEach(() => {
  delete window.matchMedia
  if (originalScrollIntoView) {
    Element.prototype.scrollIntoView = originalScrollIntoView
  } else {
    delete Element.prototype.scrollIntoView
  }
})

describe('GymAdminHolidaysPage', () => {
  it('al editar hace scroll/foco al formulario y Cancelar limpia el estado', async () => {
    renderPage()

    const [menuTrigger] = await screen.findAllByRole('button', { name: /abrir acciones/i })
    await userEvent.click(menuTrigger)
    await userEvent.click(await screen.findByRole('button', { name: /^editar$/i }))

    expect(await screen.findByText(/editando festivo #7/i)).toBeInTheDocument()
    await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' }))
    await waitFor(() => expect(screen.getByLabelText(/fecha/i)).toHaveFocus())

    await userEvent.click(screen.getByRole('button', { name: /^cancelar$/i }))

    expect(screen.getByRole('heading', { name: /^crear festivo$/i })).toBeInTheDocument()
    expect(screen.queryByText(/editando festivo #7/i)).not.toBeInTheDocument()
  })
})
