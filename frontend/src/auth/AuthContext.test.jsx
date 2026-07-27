import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'

// SIN mock de '../api/client': se usa el cliente real (con su interceptor de 401)
// y se falsea SOLO el adapter de axios, que es la capa que en producción hace la
// petición y aplica el timeout. Así el test ejercita AuthContext + interceptor +
// ProtectedRoute de verdad, y no la forma de un mock.
import api from '../api/client'
import { AuthProvider } from './AuthContext'
import ProtectedRoute from '../routes/ProtectedRoute'

const TOKEN_KEY = 'tymro_token'
const USER_KEY = 'tymro_user'

const STUDENT = { id: 7, email: 'ana@gym.cl', role: 'student', first_name: 'Ana', last_name: 'Soto' }

// Respuesta axios completa (todos los campos que axios entrega en runtime).
const okResponse = (config, data) => ({
  data,
  status: 200,
  statusText: 'OK',
  headers: {},
  config,
  request: {},
})

// OJO: al reemplazar el adapter, axios NO aplica `validateStatus` — son los
// adapters nativos (xhr/http) los que llaman a settle() y rechazan los no-2xx.
// Este helper replica ese rechazo tal como lo construye settle(), para que el
// interceptor de 401 reciba exactamente el error que ve en producción.
const httpError = (config, status, data) => {
  const response = { data, status, statusText: 'Unauthorized', headers: {}, config, request: {} }
  return new axios.AxiosError(
    `Request failed with status code ${status}`,
    'ERR_BAD_REQUEST',
    config,
    {},
    response,
  )
}

// Un timeout real de axios rechaza con AxiosError code ECONNABORTED y SIN
// `response` (nunca hubo respuesta del servidor). Se reproduce igual.
const timeoutError = (config) =>
  new axios.AxiosError(`timeout of ${config.timeout}ms exceeded`, 'ECONNABORTED', config, {})

const originalAdapter = api.defaults.adapter
const originalLocation = window.location
let assignMock

const renderApp = () =>
  render(
    <MemoryRouter initialEntries={['/student/dashboard']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<p>PANTALLA LOGIN</p>} />
          <Route
            path="/student/dashboard"
            element={
              <ProtectedRoute allowedRoles={['student']}>
                <p>CONTENIDO PRIVADO</p>
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )

beforeEach(() => {
  localStorage.clear()
  // Sesión previa guardada: es el escenario del bug (el usuario que vuelve a la
  // app con un token en localStorage es quien queda atrapado en "Cargando sesión").
  localStorage.setItem(TOKEN_KEY, 'tok-abc')
  localStorage.setItem(USER_KEY, JSON.stringify(STUDENT))

  // El interceptor de 401 usa window.location.assign/pathname; jsdom no navega.
  assignMock = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: { ...originalLocation, pathname: '/student/dashboard', assign: assignMock },
  })
})

afterEach(() => {
  api.defaults.adapter = originalAdapter
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: originalLocation,
  })
  localStorage.clear()
})

describe('AuthContext: bootstrap de sesión con /me', () => {
  it('un timeout de /me deja de cargar y ofrece reintentar, sin expulsar al login', async () => {
    api.defaults.adapter = (config) => Promise.reject(timeoutError(config))

    renderApp()

    // Ya no se queda en "Cargando sesión..." para siempre.
    await waitFor(() => {
      expect(screen.queryByText(/cargando sesión/i)).not.toBeInTheDocument()
    })

    // UI de error con salida para el usuario.
    expect(await screen.findByRole('button', { name: /reintentar/i })).toBeInTheDocument()

    // Un timeout transitorio NO es sesión inválida: no se expulsa ni se borra el token.
    expect(screen.queryByText('PANTALLA LOGIN')).not.toBeInTheDocument()
    expect(assignMock).not.toHaveBeenCalled()
    expect(localStorage.getItem(TOKEN_KEY)).toBe('tok-abc')

    // La propiedad de seguridad del cambio: no verificar la sesión NO habilita
    // renderizar la app con el usuario cacheado de localStorage.
    expect(screen.queryByText('CONTENIDO PRIVADO')).not.toBeInTheDocument()
  })

  it('un rol manipulado en localStorage no entra por la pantalla de error', async () => {
    // `tymro_user` lo controla el cliente: se puede editar a mano. Sin /me que
    // lo desmienta, la UI no debe renderizar NADA protegido.
    localStorage.setItem(USER_KEY, JSON.stringify({ ...STUDENT, role: 'superadmin' }))
    api.defaults.adapter = (config) => Promise.reject(timeoutError(config))

    renderApp()

    expect(await screen.findByRole('button', { name: /reintentar/i })).toBeInTheDocument()
    expect(screen.queryByText('CONTENIDO PRIVADO')).not.toBeInTheDocument()
  })

  it('si el reintento devuelve 401 se cierra la sesión y la pantalla de error no queda pegada', async () => {
    let attempts = 0
    api.defaults.adapter = (config) => {
      attempts += 1
      if (attempts === 1) return Promise.reject(timeoutError(config))
      return Promise.reject(httpError(config, 401, { detail: 'Invalid token.' }))
    }

    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: /reintentar/i }))

    await waitFor(() => {
      expect(assignMock).toHaveBeenCalledWith('/login')
    })
    // Con la sesión ya cerrada, seguir mostrando "Reintentar" deja al usuario en
    // un callejón sin salida: sin app, sin login y sin forma de cerrar sesión.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /reintentar/i })).not.toBeInTheDocument()
    })
    expect(screen.getByText('PANTALLA LOGIN')).toBeInTheDocument()
  })

  it('mientras el reintento está en vuelo el botón se bloquea y no duplica consultas', async () => {
    let attempts = 0
    let releaseSecondCall
    api.defaults.adapter = (config) => {
      attempts += 1
      if (attempts === 1) return Promise.reject(timeoutError(config))
      return new Promise((resolve) => {
        releaseSecondCall = () => resolve(okResponse(config, STUDENT))
      })
    }

    renderApp()
    const retry = await screen.findByRole('button', { name: /reintentar/i })
    await userEvent.click(retry)

    // Sin bloqueo, cada clic dispara un GET /me de hasta 10s: el usuario que no
    // ve feedback insiste y se come el rate-limit del backend (429) él solo.
    await waitFor(() => {
      expect(retry).toBeDisabled()
    })
    await userEvent.click(retry)
    expect(attempts).toBe(2)

    releaseSecondCall()
    expect(await screen.findByText('CONTENIDO PRIVADO')).toBeInTheDocument()
  })

  it('al reintentar tras el timeout carga la sesión y limpia el error', async () => {
    let attempts = 0
    api.defaults.adapter = (config) => {
      attempts += 1
      if (attempts === 1) return Promise.reject(timeoutError(config))
      return Promise.resolve(okResponse(config, STUDENT))
    }

    renderApp()

    const retry = await screen.findByRole('button', { name: /reintentar/i })
    await userEvent.click(retry)

    expect(await screen.findByText('CONTENIDO PRIVADO')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reintentar/i })).not.toBeInTheDocument()
    expect(attempts).toBe(2)
  })

  it('un 401 en /me sí expulsa al login y borra la sesión (interceptor)', async () => {
    api.defaults.adapter = (config) => Promise.reject(httpError(config, 401, { detail: 'Invalid token.' }))

    renderApp()

    await waitFor(() => {
      expect(assignMock).toHaveBeenCalledWith('/login')
    })
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(USER_KEY)).toBeNull()
    expect(screen.queryByRole('button', { name: /reintentar/i })).not.toBeInTheDocument()
  })
})
