import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({ getMyPlan: vi.fn() }))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'stu', first_name: 'S', last_name: 'T' } }),
}))

import { getMyPlan } from '../api/client'
import StudentDashboard from './StudentDashboard'

function plan(overrides = {}) {
  return {
    plan_name: 'Pack 10',
    total_classes: 10,
    classes_used: 2,
    remaining_classes: 8,
    start_date: '2026-07-01',
    end_date: '2026-07-30',
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
  getMyPlan.mockResolvedValue(null)
})

function renderPage() {
  return render(<MemoryRouter><StudentDashboard /></MemoryRouter>)
}

describe('StudentDashboard — estado del plan', () => {
  it('no recalcula la vigencia en el cliente: pinta la del backend', async () => {
    // `is_active && end_date >= today` con `today` sacado de toISOString() (UTC) daba
    // "Vencido" a partir de las 20:00 de Chile del último día. Acá el backend dice
    // "Vigente" con una end_date pasada: si la página vuelve a derivarla, dirá "Vencido".
    getMyPlan.mockResolvedValue(plan({ end_date: '2020-01-01', days_to_expiry: 0 }))

    renderPage()

    await waitFor(() => expect(screen.getByText('Vigente')).toBeInTheDocument())
    expect(screen.queryByText('Vencido')).not.toBeInTheDocument()
    expect(screen.queryByText('Activo')).not.toBeInTheDocument()
  })

  it('pinta el aviso del backend además de la etiqueta de estado', async () => {
    // El countdown solo puede venir de `expiry_alert_message`: la etiqueta de estado nunca
    // dice "20 dias vigentes". Sin esta aserción, borrar el badge entero dejaba la suite
    // verde, porque los otros tests los satisface el <p> de la etiqueta.
    getMyPlan.mockResolvedValue(plan())

    renderPage()

    await waitFor(() => expect(screen.getByText('20 dias vigentes')).toBeInTheDocument())
    expect(screen.getByText('20 dias vigentes')).toHaveClass('text-emerald-200')
  })

  it('muestra el estado real cuando el plan se quedó sin clases', async () => {
    getMyPlan.mockResolvedValue(plan({
      classes_used: 10,
      remaining_classes: 0,
      validity_status: 'exhausted',
      validity_status_label: 'Sin clases disponibles',
      expiry_alert_level: 'danger',
      expiry_alert_message: 'Sin clases disponibles',
    }))

    renderPage()

    await waitFor(() => expect(screen.getAllByText('Sin clases disponibles').length).toBeGreaterThan(0))
  })

  it('formatea las fechas en es-CL sin correrlas un día', async () => {
    getMyPlan.mockResolvedValue(plan())

    renderPage()

    await waitFor(() => expect(screen.getByText(/01-07-2026/)).toBeInTheDocument())
    expect(screen.getByText(/30-07-2026/)).toBeInTheDocument()
  })
})
