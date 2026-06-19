import { createContext, useContext, useEffect, useMemo, useState } from 'react'
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

  useEffect(() => {
    setAuthToken(token)
  }, [token])

  useEffect(() => {
    const bootstrap = async () => {
      if (!token) {
        setLoading(false)
        return
      }

      try {
        const currentUser = await authApi.me()
        setUser(currentUser)
        localStorage.setItem(USER_KEY, JSON.stringify(currentUser))
      } catch {
        clearSession()
      } finally {
        setLoading(false)
      }
    }

    bootstrap()
  }, [token])

  const clearSession = () => {
    setToken('')
    setUser(null)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setAuthToken(null)
  }

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
      isAuthenticated: Boolean(token && user),
      login,
      loginWithToken,
      logout,
      refreshMe,
    }),
    [token, user, loading],
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
