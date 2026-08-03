import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  assignPlanToUser: vi.fn(),
  getPlans: vi.fn(),
  usersApi: { list: vi.fn() },
}))

let mockUser
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}))

import { assignPlanToUser, getPlans, usersApi } from '../api/client'
import AssignPlanPage from './AssignPlanPage'

const student = { id: 7, first_name: 'Ana', last_name: 'López', username: 'ana' }
const activePlan = {
  id: 3,
  name: 'Pack 10',
  price: 20000,
  discount_percentage: 10,
  total_classes: 10,
  unlimited_classes: false,
  is_active: true,
}

function renderPage() {
  return render(<MemoryRouter><AssignPlanPage /></MemoryRouter>)
}

async function fillUserAndPlan() {
  await screen.findByRole('option', { name: 'Ana López' })
  await userEvent.selectOptions(screen.getByLabelText('Alumno'), '7')
  await userEvent.selectOptions(screen.getByLabelText('Plan'), '3')
}

beforeEach(() => {
  vi.clearAllMocks()
  mockUser = { role: 'gym_admin' }
  usersApi.list.mockResolvedValue([student])
  getPlans.mockResolvedValue([activePlan])
  assignPlanToUser.mockResolvedValue({})
})

describe('AssignPlanPage — vía de pago', () => {
  it('vía gratis: el payload manda payment.method=free y NO lleva discount_percentage ni amount', async () => {
    renderPage()
    await fillUserAndPlan()

    await userEvent.click(screen.getByRole('button', { name: 'Gratis (beca / cortesía)' }))
    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    await waitFor(() => expect(assignPlanToUser).toHaveBeenCalled())
    const payload = assignPlanToUser.mock.calls[0][0]
    expect(payload.payment).toEqual({ method: 'free' })
    // Aserción sobre las CLAVES, no solo el valor: el backend rechaza (400) si
    // discount_percentage/amount viajan junto a un pago free, aunque el valor sea 0/undefined.
    expect(Object.keys(payload)).not.toContain('discount_percentage')
    expect(Object.keys(payload.payment)).not.toContain('amount')
  })

  it('vía pago (default): manda discount_percentage y payment.method=manual con monto y referencia', async () => {
    renderPage()
    await fillUserAndPlan()

    await userEvent.type(screen.getByLabelText('Monto cobrado'), '20000')
    await userEvent.type(screen.getByLabelText('Referencia (opcional)'), 'transferencia caja 2')
    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    await waitFor(() => expect(assignPlanToUser).toHaveBeenCalled())
    const payload = assignPlanToUser.mock.calls[0][0]
    expect(payload.payment).toEqual({ method: 'manual', amount: '20000', reference: 'transferencia caja 2' })
    expect(Object.keys(payload)).toContain('discount_percentage')
  })

  it('vía pago con monto vacío, 0 o negativo: no llama a la API y muestra el error local', async () => {
    renderPage()
    await fillUserAndPlan()

    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))
    // Matcheamos el mensaje de error puntual (no /monto/i a secas: eso también matchea
    // la etiqueta del campo "Monto cobrado" y la query queda ambigua).
    expect(await screen.findByText(/monto válido/i)).toBeInTheDocument()
    expect(assignPlanToUser).not.toHaveBeenCalled()

    await userEvent.type(screen.getByLabelText('Monto cobrado'), '0')
    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))
    expect(assignPlanToUser).not.toHaveBeenCalled()

    await userEvent.clear(screen.getByLabelText('Monto cobrado'))
    await userEvent.type(screen.getByLabelText('Monto cobrado'), '-5')
    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))
    expect(assignPlanToUser).not.toHaveBeenCalled()
  })

  it('vía pago con conceptos adicionales: agrega filas y el payload manda payment.line_items bien formado', async () => {
    renderPage()
    await fillUserAndPlan()

    await userEvent.type(screen.getByLabelText('Monto cobrado'), '20000')

    await userEvent.click(screen.getByRole('button', { name: 'Agregar concepto' }))
    await userEvent.click(screen.getByRole('button', { name: 'Agregar concepto' }))
    await userEvent.type(screen.getByLabelText('Concepto 1'), 'Pesas')
    await userEvent.type(screen.getByLabelText('Monto concepto 1'), '3000')
    await userEvent.type(screen.getByLabelText('Concepto 2'), 'Toalla')
    await userEvent.type(screen.getByLabelText('Monto concepto 2'), '2000')

    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    await waitFor(() => expect(assignPlanToUser).toHaveBeenCalled())
    const payload = assignPlanToUser.mock.calls[0][0]
    expect(payload.payment).toEqual({
      method: 'manual',
      amount: '20000',
      reference: '',
      line_items: [
        { concept: 'Pesas', amount: '3000' },
        { concept: 'Toalla', amount: '2000' },
      ],
    })
  })

  it('vía pago: "Quitar" saca la fila y no viaja en el payload', async () => {
    renderPage()
    await fillUserAndPlan()

    await userEvent.type(screen.getByLabelText('Monto cobrado'), '20000')
    await userEvent.click(screen.getByRole('button', { name: 'Agregar concepto' }))
    await userEvent.type(screen.getByLabelText('Concepto 1'), 'Pesas')
    await userEvent.type(screen.getByLabelText('Monto concepto 1'), '3000')
    await userEvent.click(screen.getByRole('button', { name: 'Quitar concepto 1' }))

    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    await waitFor(() => expect(assignPlanToUser).toHaveBeenCalled())
    const payload = assignPlanToUser.mock.calls[0][0]
    expect(Object.keys(payload.payment)).not.toContain('line_items')
  })

  it('vía pago con una fila a medio llenar (solo concepto o solo monto): no llama a la API y muestra el error', async () => {
    renderPage()
    await fillUserAndPlan()

    await userEvent.type(screen.getByLabelText('Monto cobrado'), '20000')
    await userEvent.click(screen.getByRole('button', { name: 'Agregar concepto' }))
    await userEvent.type(screen.getByLabelText('Concepto 1'), 'Pesas')
    // Monto concepto 1 queda vacío a propósito.

    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    expect(await screen.findByText(/cada concepto adicional/i)).toBeInTheDocument()
    expect(assignPlanToUser).not.toHaveBeenCalled()
  })

  it('vía gratis: oculta "Conceptos adicionales" y descarta cualquier fila cargada antes de cambiar de vía', async () => {
    renderPage()
    await fillUserAndPlan()

    // Carga una fila estando en la vía manual (default de gym_admin)...
    await userEvent.click(screen.getByRole('button', { name: 'Agregar concepto' }))
    await userEvent.type(screen.getByLabelText('Concepto 1'), 'Pesas')
    await userEvent.type(screen.getByLabelText('Monto concepto 1'), '3000')

    // ...y cambia a la vía gratis: la sección desaparece.
    await userEvent.click(screen.getByRole('button', { name: 'Gratis (beca / cortesía)' }))
    expect(screen.queryByText('Conceptos adicionales')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    await waitFor(() => expect(assignPlanToUser).toHaveBeenCalled())
    const payload = assignPlanToUser.mock.calls[0][0]
    expect(payload.payment).toEqual({ method: 'free' })
    expect(Object.keys(payload.payment)).not.toContain('line_items')
  })

  it('superadmin: no ve "Registrar pago" y el submit manda payment.method=free', async () => {
    mockUser = { role: 'superadmin' }
    renderPage()
    await fillUserAndPlan()

    expect(screen.queryByRole('button', { name: 'Registrar pago' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Asignar plan' }))

    await waitFor(() => expect(assignPlanToUser).toHaveBeenCalled())
    const payload = assignPlanToUser.mock.calls[0][0]
    expect(payload.payment).toEqual({ method: 'free' })
  })
})
