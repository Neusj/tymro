import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  getPlanById: vi.fn(),
  getPlanMemberships: vi.fn(),
  removePlanMembership: vi.fn(),
}))

import { getPlanById, getPlanMemberships } from '../api/client'
import GymAdminPlanMembershipsPage from './GymAdminPlanMembershipsPage'

function membership(overrides = {}) {
  return {
    id: 1,
    user: 1,
    user_name: 'Ana',
    user_email: 'ana@test.local',
    start_date: '2026-07-01',
    end_date: '2026-07-30',
    total_classes: 10,
    classes_used: 0,
    remaining_classes: 10,
    validity_status: 'active',
    validity_status_label: 'Vigente',
    days_to_expiry: 20,
    expiry_alert_level: 'safe',
    expiry_alert_message: '20 dias vigentes',
    is_active: true,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getPlanById.mockResolvedValue({ id: 7, name: 'Pack 10' })
  getPlanMemberships.mockResolvedValue([])
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
  return render(<MemoryRouter><GymAdminPlanMembershipsPage /></MemoryRouter>)
}

function kpi(name) {
  // Cada KPI es <p>rótulo</p><p>valor</p> dentro de la misma tarjeta.
  return screen.getByText(name).parentElement
}

// DataTable pinta la tabla de escritorio Y las tarjetas móviles a la vez (las alterna por
// CSS), asi que cada celda aparece dos veces en el DOM: siempre se cuenta, nunca se asume una.
const shown = (text) => screen.queryAllByText(text).length

describe('GymAdminPlanMembershipsPage — KPI vs columna Estado', () => {
  it('cuenta como activas solo las vigentes, no todo el histórico con is_active', async () => {
    // `activate_student_plan` deja is_active=True para siempre ("no fue reemplazada"), así
    // que contarlo daba "3 activas" sobre una tabla donde 2 filas dicen Vencido.
    getPlanMemberships.mockResolvedValue([
      membership({ id: 1, user: 1, user_name: 'Ana' }),
      membership({
        id: 2,
        user: 2,
        user_name: 'Beto',
        is_active: true,
        validity_status: 'expired',
        validity_status_label: 'Vencido',
        expiry_alert_level: 'expired',
        expiry_alert_message: 'Vencido',
      }),
      membership({
        id: 3,
        user: 3,
        user_name: 'Caro',
        is_active: true,
        validity_status: 'expired',
        validity_status_label: 'Vencido',
        expiry_alert_level: 'expired',
        expiry_alert_message: 'Vencido',
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Ana')).toBeGreaterThan(0))
    expect(within(kpi('Total membresias')).getByText('3')).toBeInTheDocument()
    expect(within(kpi('Membresias activas')).getByText('1')).toBeInTheDocument()
  })

  it('no cuenta como activa una membresía por iniciar (is_active ya es true)', async () => {
    getPlanMemberships.mockResolvedValue([
      membership({
        is_active: true,
        validity_status: 'upcoming',
        validity_status_label: 'Por iniciar',
        expiry_alert_level: 'safe',
        expiry_alert_message: 'Por iniciar',
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Ana')).toBeGreaterThan(0))
    expect(within(kpi('Membresias activas')).getByText('0')).toBeInTheDocument()
    expect(shown('Por iniciar')).toBeGreaterThan(0)
  })

  it('pinta la etiqueta del backend para los estados que el ladder no conocía', async () => {
    // El `else` de :104-111 mandaba exhausted/enrollment_fee_unpaid a "Inactiva".
    getPlanMemberships.mockResolvedValue([
      membership({
        classes_used: 10,
        remaining_classes: 0,
        validity_status: 'exhausted',
        validity_status_label: 'Sin clases disponibles',
        expiry_alert_level: 'danger',
        expiry_alert_message: 'Sin clases disponibles',
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Sin clases disponibles')).toBeGreaterThan(0))
    expect(shown('Inactiva')).toBe(0)
  })

  it('el Estado se pinta como chip con color, no como texto pelado', async () => {
    // En móvil DataTable manda esta celda a la zona `meta`, que no aporta estilo: si el
    // render devuelve un string, la tarjeta se queda SIN ninguna señal de color.
    getPlanMemberships.mockResolvedValue([
      membership({
        validity_status: 'expired',
        validity_status_label: 'Vencido',
        expiry_alert_level: 'expired',
        expiry_alert_message: 'Vencido',
      }),
    ])

    renderPage()

    await waitFor(() => expect(shown('Vencido')).toBeGreaterThan(0))
    screen.getAllByText('Vencido').forEach((node) => expect(node).toHaveClass('text-red-200'))
  })

  it('muestra el aviso de vencimiento además de la etiqueta de estado', async () => {
    getPlanMemberships.mockResolvedValue([membership()])

    renderPage()

    await waitFor(() => expect(shown('Vigente')).toBeGreaterThan(0))
    expect(shown('20 dias vigentes')).toBeGreaterThan(0)
  })

  it('muestra las fechas sin correrlas un día (bug UTC)', async () => {
    getPlanMemberships.mockResolvedValue([membership()])

    renderPage()

    await waitFor(() => expect(shown('01-07-2026')).toBeGreaterThan(0))
    expect(shown('30-07-2026')).toBeGreaterThan(0)
    expect(shown('30-06-2026')).toBe(0)
    expect(shown('29-07-2026')).toBe(0)
  })
})
