import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  getMyMemberships: vi.fn(),
  paymentsApi: { checkout: vi.fn() },
}))

import { getMyMemberships } from '../api/client'
import StudentPlansPage from './StudentPlansPage'

// Fila tal como la manda StudentPlanSerializer despues de 7.3.
function membership(overrides = {}) {
  return {
    id: 1,
    plan_name: 'Pack 10',
    start_date: '2026-07-01',
    end_date: '2026-07-30',
    total_classes: 10,
    classes_used: 2,
    remaining_classes: 8,
    validity_status: 'active',
    validity_status_label: 'Vigente',
    days_to_expiry: 20,
    expiry_alert_level: 'safe',
    expiry_alert_message: '20 dias vigentes',
    enrollment_fee: 0,
    enrollment_fee_status: { status: 'waived' },
    is_active: true,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getMyMemberships.mockResolvedValue([])
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

function renderPage() {
  return render(<MemoryRouter><StudentPlansPage /></MemoryRouter>)
}

// DataTable pinta la tabla de escritorio Y las tarjetas móviles a la vez (las alterna por
// CSS), asi que cada celda aparece dos veces en el DOM: siempre se cuenta, nunca se asume una.
const shown = (text) => screen.queryAllByText(text).length

describe('StudentPlansPage — estado de la membresía', () => {
  it('pinta la etiqueta del backend en vez de colapsar todo a Vencido', async () => {
    // El colapso de :101 (`validity_status === 'active' ? 'active' : 'expired'`) mostraba
    // "Vencido" a un plan que sigue dentro de su ventana y solo se quedó sin clases.
    getMyMemberships.mockResolvedValue([
      membership({
        remaining_classes: 0,
        classes_used: 10,
        validity_status: 'exhausted',
        validity_status_label: 'Sin clases disponibles',
        expiry_alert_level: 'danger',
        expiry_alert_message: 'Sin clases disponibles',
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Sin clases disponibles')).toBeGreaterThan(0))
    expect(shown('Vencido')).toBe(0)
  })

  it('muestra "Matrícula impaga" junto al botón de pago, no "Vencido"', async () => {
    getMyMemberships.mockResolvedValue([
      membership({
        enrollment_fee: 15000,
        enrollment_fee_status: { status: 'pending', due_at: null },
        validity_status: 'enrollment_fee_unpaid',
        validity_status_label: 'Matrícula impaga',
        expiry_alert_level: 'danger',
        expiry_alert_message: 'Matrícula impaga',
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Matrícula impaga')).toBeGreaterThan(0))
    expect(screen.getAllByRole('button', { name: /Pagar matrícula/ }).length).toBeGreaterThan(0)
    expect(shown('Vencido')).toBe(0)
  })

  it('sigue mostrando "Vigente" y su cuenta regresiva para un plan sano', async () => {
    getMyMemberships.mockResolvedValue([membership()])

    renderPage()

    await waitFor(() => expect(shown('Vigente')).toBeGreaterThan(0))
    expect(shown('20 dias vigentes')).toBeGreaterThan(0)
  })

  it('muestra "Congelada" si hay congelamiento abierto aunque el backend marque Vigente', async () => {
    getMyMemberships.mockResolvedValue([
      membership({
        active_freeze: { id: 5, start_date: '2026-08-20', planned_end_date: '2026-08-30' },
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Congelada')).toBeGreaterThan(0))
    expect(shown('Vigente')).toBe(0)
  })

  it('el Estado se pinta como chip con color, no como texto pelado', async () => {
    // En móvil DataTable manda esta celda a la zona `meta`, que no aporta estilo: si el
    // render devuelve un string, la tarjeta se queda SIN ninguna señal de color.
    getMyMemberships.mockResolvedValue([membership()])

    renderPage()

    await waitFor(() => expect(shown('Vigente')).toBeGreaterThan(0))
    screen.getAllByText('Vigente').forEach((node) => expect(node).toHaveClass('text-emerald-200'))
  })

  it('muestra las fechas sin correrlas un día (bug UTC)', async () => {
    getMyMemberships.mockResolvedValue([membership()])

    renderPage()

    await waitFor(() => expect(shown('01-07-2026')).toBeGreaterThan(0))
    expect(shown('30-07-2026')).toBeGreaterThan(0)
    expect(shown('30-06-2026')).toBe(0)
    expect(shown('29-07-2026')).toBe(0)
  })
})
