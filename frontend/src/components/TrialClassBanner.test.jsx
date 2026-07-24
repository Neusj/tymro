import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mismo patrón que RutReminderBanner.test.jsx: se mockea useAuth para inyectar el
// `user`. El componente usa <Link>, así que se envuelve en MemoryRouter.
let mockUser
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}))

import TrialClassBanner from './TrialClassBanner'

function renderBanner() {
  return render(
    <MemoryRouter>
      <TrialClassBanner />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockUser = null
})

describe('TrialClassBanner', () => {
  it('alumno verificado que no usó la prueba: muestra el CTA para agendar en /trial', () => {
    mockUser = { role: 'student', email_verified: true, has_used_trial: false }
    renderBanner()
    expect(screen.getByText(/clase de prueba gratis/i)).toBeInTheDocument()
    const cta = screen.getByRole('link', { name: /agéndala/i })
    expect(cta).toHaveAttribute('href', '/trial')
  })

  it('oculto si el alumno YA usó su clase de prueba', () => {
    mockUser = { role: 'student', email_verified: true, has_used_trial: true }
    const { container } = renderBanner()
    expect(container).toBeEmptyDOMElement()
  })

  it('alumno sin email verificado: variante "confirma tu correo", sin CTA a /trial', () => {
    mockUser = { role: 'student', email_verified: false, has_used_trial: false }
    renderBanner()
    expect(screen.getByText(/confirma tu correo/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /agéndala/i })).not.toBeInTheDocument()
  })

  it('oculto para roles que no son alumno', () => {
    mockUser = { role: 'gym_admin', email_verified: true, has_used_trial: false }
    const { container } = renderBanner()
    expect(container).toBeEmptyDOMElement()
  })

  it('oculto sin usuario en sesión', () => {
    mockUser = null
    const { container } = renderBanner()
    expect(container).toBeEmptyDOMElement()
  })
})
