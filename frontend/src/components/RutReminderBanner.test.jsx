import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const refreshMe = vi.fn()
let mockUser
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, refreshMe }),
}))
vi.mock('../api/client', () => ({
  authApi: { updateMe: vi.fn() },
}))

import { authApi } from '../api/client'
import RutReminderBanner from './RutReminderBanner'

beforeEach(() => {
  vi.clearAllMocks()
  mockUser = null
})

describe('RutReminderBanner', () => {
  it('no se muestra si el usuario ya tiene RUT', () => {
    mockUser = { role: 'student', rut: '12345678-5' }
    const { container } = render(<RutReminderBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it('no se muestra para roles de plataforma (superadmin)', () => {
    mockUser = { role: 'superadmin', rut: null }
    const { container } = render(<RutReminderBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it('se muestra para un usuario de organización sin RUT', () => {
    mockUser = { role: 'student', rut: null }
    render(<RutReminderBanner />)
    expect(screen.getByText('Completa tu RUT')).toBeInTheDocument()
  })

  it('se muestra para un profesor de organizacion sin RUT', () => {
    mockUser = { role: 'teacher', rut: null }
    render(<RutReminderBanner />)
    expect(screen.getByText('Completa tu RUT')).toBeInTheDocument()
  })

  it('RUT inválido: muestra error y no llama al API', async () => {
    mockUser = { role: 'student', rut: null }
    render(<RutReminderBanner />)
    fireEvent.change(screen.getByLabelText('RUT'), { target: { value: '123456789' } })
    await userEvent.click(screen.getByRole('button', { name: /guardar/i }))
    expect(await screen.findByText(/RUT inválido/i)).toBeInTheDocument()
    expect(authApi.updateMe).not.toHaveBeenCalled()
  })

  it('RUT válido: envía canónico y refresca la sesión', async () => {
    mockUser = { role: 'student', rut: null }
    authApi.updateMe.mockResolvedValue({})
    render(<RutReminderBanner />)
    fireEvent.change(screen.getByLabelText('RUT'), { target: { value: '123456785' } })
    await userEvent.click(screen.getByRole('button', { name: /guardar/i }))
    await waitFor(() => expect(authApi.updateMe).toHaveBeenCalledWith({ rut: '12345678-5' }))
    await waitFor(() => expect(refreshMe).toHaveBeenCalled())
  })
})
