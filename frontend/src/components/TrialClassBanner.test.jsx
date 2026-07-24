import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mismo patrón que RutReminderBanner.test.jsx: se mockea useAuth para inyectar el
// `user`. El componente usa <Link>, así que se envuelve en MemoryRouter.
let mockUser
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}))

// El botón de reenvío (#26) llama a authApi.resendVerification por la instancia
// axios AUTENTICADA (client.js). Lo mockeamos para controlar resolución/rechazo.
vi.mock('../api/client', () => ({
  authApi: { resendVerification: vi.fn() },
}))

import TrialClassBanner from './TrialClassBanner'
import { authApi } from '../api/client'

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

describe('TrialClassBanner — reenvío de confirmación (#26)', () => {
  beforeEach(() => {
    mockUser = { role: 'student', email_verified: false, has_used_trial: false }
    authApi.resendVerification.mockReset()
  })

  it('rama no verificada: ofrece un botón para reenviar el correo (idle)', () => {
    renderBanner()
    expect(screen.getByRole('button', { name: /reenviar/i })).toBeInTheDocument()
  })

  it('al reenviar transiciona enviando → enviado y llama a la API una sola vez', async () => {
    let resolvePost
    authApi.resendVerification.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve
      }),
    )
    renderBanner()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /reenviar/i }))

    // En vuelo: estado "enviando" y botón deshabilitado (evita doble envío).
    expect(screen.getByRole('button', { name: /enviando/i })).toBeDisabled()

    resolvePost({ detail: 'ok' })

    expect(await screen.findByText(/te reenviamos/i)).toBeInTheDocument()
    expect(authApi.resendVerification).toHaveBeenCalledTimes(1)
  })

  it('429: informa que ya enviamos uno recién', async () => {
    authApi.resendVerification.mockRejectedValue({ response: { status: 429 } })
    renderBanner()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /reenviar/i }))

    expect(await screen.findByText(/ya enviamos uno recién/i)).toBeInTheDocument()
  })

  it('no toca la rama verificada (sigue el CTA a /trial, sin botón de reenvío)', () => {
    mockUser = { role: 'student', email_verified: true, has_used_trial: false }
    renderBanner()
    expect(screen.getByRole('link', { name: /agéndala/i })).toHaveAttribute('href', '/trial')
    expect(screen.queryByRole('button', { name: /reenviar/i })).not.toBeInTheDocument()
  })
})
