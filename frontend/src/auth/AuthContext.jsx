import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authApi, setAuthToken } from '../api/client'

const AuthContext = createContext(null)

const TOKEN_KEY = 'tymro_token'
const USER_KEY = 'tymro_user'

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || '')
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem(USER_KEY)
    return saved ? JSON.parse(saved) : null
  })
  const [loading, setLoading] = useState(Boolean(token))
  // Fallo transitorio verificando la sesión (timeout/red/5xx). NO es sesión
  // inválida: se expone para que la UI ofrezca reintentar en vez de expulsar.
  const [bootstrapError, setBootstrapError] = useState('')
  // Hay una verificación de /me en vuelo. Sin esto el botón de reintentar acepta
  // clics repetidos (cada uno un GET de hasta 10s) y el usuario se gana un 429.
  const [verifying, setVerifying] = useState(false)

  useEffect(() => {
    setAuthToken(token)
  }, [token])

  const clearSession = useCallback(() => {
    setToken('')
    setUser(null)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setAuthToken(null)
    // Si no se limpia, la pantalla de "reintentar" sobrevive a la sesión cerrada
    // y tapa el redirect al login: el usuario queda sin app y sin salida.
    setBootstrapError('')
  }, [])

  const bootstrap = useCallback(async () => {
    if (!token) {
      setLoading(false)
      return
    }

    setVerifying(true)
    try {
      const currentUser = await authApi.me()
      setUser(currentUser)
      localStorage.setItem(USER_KEY, JSON.stringify(currentUser))
      setBootstrapError('')
    } catch (error) {
      // 401 = el token ya no vale: el interceptor de client.js limpia la sesión
      // y redirige a /login. Se replica el clearSession local para dejar el
      // estado de React coherente (el interceptor solo toca localStorage).
      if (error?.response?.status === 401) {
        clearSession()
        return
      }
      // Timeout, red caída o 5xx: la sesión puede seguir siendo válida. No se
      // borra el token; el usuario decide reintentar.
      setBootstrapError('No pudimos verificar tu sesión. Revisá tu conexión e intentá de nuevo.')
    } finally {
      setLoading(false)
      setVerifying(false)
    }
  }, [token, clearSession])

  useEffect(() => {
    bootstrap()
  }, [bootstrap])

  const login = async (email, password) => {
    const data = await authApi.login({ email, password })
    const sessionToken = data.token
    const currentUser = data.user

    setToken(sessionToken)
    setUser(currentUser)
    localStorage.setItem(TOKEN_KEY, sessionToken)
    localStorage.setItem(USER_KEY, JSON.stringify(currentUser))
    setAuthToken(sessionToken)

    return currentUser
  }

  // Inicia sesión con un token ya emitido por el servidor (ej. tras verificar el
  // email en el registro público). No toca el contrato de `login`.
  const loginWithToken = (sessionToken, currentUser) => {
    setToken(sessionToken)
    setUser(currentUser)
    localStorage.setItem(TOKEN_KEY, sessionToken)
    localStorage.setItem(USER_KEY, JSON.stringify(currentUser))
    setAuthToken(sessionToken)
    return currentUser
  }

  const logout = async () => {
    try {
      await authApi.logout()
    } catch {
      // noop: clear local session even if token already expired
    }
    clearSession()
  }

  const refreshMe = async () => {
    const currentUser = await authApi.me()
    setUser(currentUser)
    localStorage.setItem(USER_KEY, JSON.stringify(currentUser))
    return currentUser
  }

  const value = useMemo(
    () => ({
      token,
      user,
      loading,
      bootstrapError,
      verifying,
      retryBootstrap: bootstrap,
      isAuthenticated: Boolean(token && user),
      login,
      loginWithToken,
      logout,
      refreshMe,
    }),
    [token, user, loading, bootstrapError, verifying, bootstrap],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return ctx
}
