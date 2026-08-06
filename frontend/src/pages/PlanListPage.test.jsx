import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Planes 100% gratuitos (discount_percentage=100): el pago al profesor sale de un valor
// configurable por organización (teacher-payment-config). El front intercala un chequeo de
// esa config ANTES de mandar el POST — ver PlanListPage.jsx `submit`.
vi.mock('../api/client', () => ({
  createPlan: vi.fn(),
  updatePlan: vi.fn(),
  removePlan: vi.fn(),
  getPlans: vi.fn(),
  organizationsApi: { list: vi.fn() },
  teacherPaymentConfigApi: { get: vi.fn(), update: vi.fn() },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'gym_admin', organization: 7 } }),
}))

import {
  createPlan,
  getPlans,
  teacherPaymentConfigApi,
} from '../api/client'
import PlanListPage from './PlanListPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <PlanListPage />
    </MemoryRouter>,
  )
}

async function openCreateAndFillFreePlan(user, discount = '100') {
  await user.click(screen.getByRole('button', { name: 'Crear plan' }))
  await user.type(screen.getByRole('textbox', { name: 'Nombre' }), 'Plan Gratis')
  const discountInput = screen.getByLabelText('Descuento %')
  await user.clear(discountInput)
  await user.type(discountInput, discount)
}

beforeEach(() => {
  vi.clearAllMocks()
  getPlans.mockResolvedValue([])
  createPlan.mockResolvedValue({ name: 'Plan Gratis' })
  // DataTable consulta matchMedia al montar; jsdom no lo implementa (mismo patrón que
  // GymAdminBranchesPage.test.jsx / GymAdminClassTemplatesPage.test.jsx).
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

describe('PlanListPage — plan gratuito con config en 0 (modal bloqueante)', () => {
  it('bloquea el guardado y NO llama a createPlan', async () => {
    teacherPaymentConfigApi.get.mockResolvedValue({ free_class_teacher_payment_value: 0 })
    renderPage()
    await waitFor(() => expect(getPlans).toHaveBeenCalled())
    const user = userEvent.setup()

    await openCreateAndFillFreePlan(user)
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/no puedes crear planes gratuitos/i)).toBeInTheDocument()
    expect(teacherPaymentConfigApi.get).toHaveBeenCalledWith(7)
    expect(createPlan).not.toHaveBeenCalled()
  })

  it('el modal bloqueante ofrece un acceso a la pantalla de configuración', async () => {
    teacherPaymentConfigApi.get.mockResolvedValue({ free_class_teacher_payment_value: 0 })
    renderPage()
    await waitFor(() => expect(getPlans).toHaveBeenCalled())
    const user = userEvent.setup()

    await openCreateAndFillFreePlan(user)
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByRole('button', { name: 'Ir a configuración' })).toBeInTheDocument()
    expect(createPlan).not.toHaveBeenCalled()
  })
})

describe('PlanListPage — plan gratuito con config > 0 (modal de confirmación)', () => {
  it('Cancelar no llama a createPlan; Aceptar sí lo llama con el payload esperado', async () => {
    teacherPaymentConfigApi.get.mockResolvedValue({ free_class_teacher_payment_value: 5000 })
    renderPage()
    await waitFor(() => expect(getPlans).toHaveBeenCalled())
    const user = userEvent.setup()

    await openCreateAndFillFreePlan(user)
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText(/este plan es gratuito/i)).toBeInTheDocument()
    expect(screen.getByText(/\$5\.000/)).toBeInTheDocument()

    // Cancelar: aborta, no se envía nada.
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(createPlan).not.toHaveBeenCalled()
    expect(screen.queryByText(/este plan es gratuito/i)).not.toBeInTheDocument()

    // Reintenta y esta vez confirma.
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(await screen.findByText(/este plan es gratuito/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Aceptar' }))

    await waitFor(() =>
      expect(createPlan).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Plan Gratis', discount_percentage: 100 }),
      ),
    )
  })
})

describe('PlanListPage — plan NO gratuito (centinela de no-regresión)', () => {
  it('con descuento parcial no aparece ningún modal y guarda directo', async () => {
    renderPage()
    await waitFor(() => expect(getPlans).toHaveBeenCalled())
    const user = userEvent.setup()

    await openCreateAndFillFreePlan(user, '50')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(createPlan).toHaveBeenCalled())
    expect(teacherPaymentConfigApi.get).not.toHaveBeenCalled()
    expect(screen.queryByText(/este plan es gratuito/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/no puedes crear planes gratuitos/i)).not.toBeInTheDocument()
  })

  it('con descuento 0 (default) no aparece ningún modal y guarda directo', async () => {
    renderPage()
    await waitFor(() => expect(getPlans).toHaveBeenCalled())
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Crear plan' }))
    await user.type(screen.getByRole('textbox', { name: 'Nombre' }), 'Plan Normal')
    await user.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(createPlan).toHaveBeenCalled())
    expect(teacherPaymentConfigApi.get).not.toHaveBeenCalled()
  })
})
