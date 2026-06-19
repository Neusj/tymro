/**
 * Helpers de la suite multi-org.
 *
 * Los specs de API NO usan DNS de *.localhost (Node en Windows no lo resuelve):
 * conectan a 127.0.0.1:8000 y mandan `X-Forwarded-Host: <sub>.localhost`.
 * El backend tiene USE_X_FORWARDED_HOST=True, así que OrganizationMiddleware
 * resuelve la org desde ese header igual que en producción desde el Host real.
 * Los specs de navegador SÍ usan *.localhost (Chromium resuelve *.localhost).
 */
import { request } from '@playwright/test'

const API_HOST = process.env.QA_BACKEND_URL || 'http://127.0.0.1:8000'
const API_BASE = `${API_HOST.replace(/\/$/, '')}/api/`

// Hosts de tenant (subdominio.localhost). 'localhost' = apex/plataforma.
export const HOSTS = {
  apex: 'localhost',
  r2b: 'r2b-qa.localhost',
  gymTest: 'gym-test.localhost',
  e2eGym: 'e2e-gym.localhost',
  unknown: 'no-existe.localhost',
}

// Credenciales del seed (--org=all). Emails se repiten entre orgs a propósito;
// el subdominio los desambigua.
export const CREDS = {
  superadmin: { email: 'superadmin@tymro.local', password: 'superadmin123' },
  r2bStudent: { email: 'student1@tymro.local', password: 'student123' },
  r2bGymAdmin: { email: 'gymadmin@tymro.local', password: 'gymadmin123' },
  gymTestGymAdmin: { email: 'gymadmin@tymro.local', password: 'gymadmin123' },
  e2eGymAdmin: { email: 'gymadmin@tymro.local', password: 'gymadmin123' },
  // Email COMPARTIDO: alumno en r2b-qa, profesor en gym-test.
  sharedR2bStudent: { email: 'juan@demo.local', password: 'student123' },
  sharedGymTestTeacher: { email: 'juan@demo.local', password: 'teacher123' },
}

/** Contexto de request para un host de tenant (opcionalmente autenticado). */
export async function apiContext({ host = HOSTS.apex, token = null } = {}) {
  const headers = { 'X-Forwarded-Host': host }
  if (token) {
    headers.Authorization = `Token ${token}`
  }
  return request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: headers,
  })
}

/** Login por email contra un host de tenant. Devuelve { status, body, token }. */
export async function apiLogin({ host = HOSTS.apex, email, password }) {
  const ctx = await apiContext({ host })
  const res = await ctx.post('login/', { data: { email, password } })
  const status = res.status()
  let body = null
  try {
    body = await res.json()
  } catch {
    body = await res.text()
  }
  await ctx.dispose()
  return { status, body, token: body && body.token }
}

/** Id de organización por slug (consultado como superadmin desde el apex). */
export async function getOrgIdBySlug(token, slug) {
  const ctx = await apiContext({ host: HOSTS.apex, token })
  const res = await ctx.get('organizations/')
  const data = await res.json()
  await ctx.dispose()
  const list = Array.isArray(data) ? data : data.results || []
  const org = list.find((o) => o.slug === slug)
  return org && org.id
}

/** Login de superadmin en el apex; devuelve el token (lanza si falla). */
export async function superadminToken() {
  const { status, token } = await apiLogin({
    host: HOSTS.apex, email: CREDS.superadmin.email, password: CREDS.superadmin.password,
  })
  if (status !== 200 || !token) {
    throw new Error(`No se pudo loguear superadmin (status ${status}).`)
  }
  return token
}

/** Construye un storageState de Playwright para un origen (SPA en un subdominio). */
export function buildStorageState(origin, token, user) {
  return {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [
          { name: 'tymro_token', value: token },
          { name: 'tymro_user', value: JSON.stringify(user) },
        ],
      },
    ],
  }
}
