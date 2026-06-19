import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { request } from '@playwright/test'
import dotenv from 'dotenv'

dotenv.config()

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.join(__dirname, '..')
const FIXTURES_PATH = path.join(ROOT, '.fixtures.json')
const STORAGE_PATH = path.join(ROOT, 'storageState.student.json')
const TEACHER_STORAGE_PATH = path.join(ROOT, 'storageState.teacher.json')

export const baseURL = (process.env.QA_BASE_URL || 'https://qa.tymroapp.com').replace(/\/$/, '')
export const apiURL = (process.env.QA_API_URL || `${baseURL}/api`).replace(/\/$/, '')

export const creds = {
  student: {
    username: process.env.QA_USER || 'student1',
    password: process.env.QA_PASSWORD || 'student123',
  },
  gymAdmin: {
    username: process.env.QA_GYM_ADMIN_USER || 'gymadmin',
    password: process.env.QA_GYM_ADMIN_PASSWORD || 'gymadmin123',
  },
  teacher: {
    username: process.env.QA_TEACHER_USER || 'teacher1',
    password: process.env.QA_TEACHER_PASSWORD || 'teacher123',
  },
}

export function loadFixtures() {
  if (!fs.existsSync(FIXTURES_PATH)) {
    throw new Error('Falta e2e/.fixtures.json. ¿Corrió global-setup (el seed)?')
  }
  return JSON.parse(fs.readFileSync(FIXTURES_PATH, 'utf8'))
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// baseURL con slash final: así las rutas relativas (sin slash inicial) se resuelven
// DENTRO de /api/ (Playwright usa new URL(); una ruta '/x' iría al origen y saltaría /api).
const API_BASE = apiURL.endsWith('/') ? apiURL : `${apiURL}/`

// Login por API tolerante al throttle de /login/ (scope 'login' = 5/min). Ante un
// 429 espera el Retry-After (o 15s) y reintenta. Devuelve { token, user, ctx }.
export async function apiLogin(username, password, { retries = 4 } = {}) {
  const ctx = await request.newContext({ baseURL: API_BASE, ignoreHTTPSErrors: true })
  for (let attempt = 0; ; attempt += 1) {
    const res = await ctx.post('login/', { data: { username, password } })
    if (res.status() === 429 && attempt < retries) {
      const wait = (Number(res.headers()['retry-after']) || 15) + 1
      console.log(`[apiLogin] 429 para "${username}" → espera ${wait}s y reintenta...`)
      await sleep(wait * 1000)
      continue
    }
    if (!res.ok()) {
      const text = await res.text()
      await ctx.dispose()
      throw new Error(`Login API falló (${res.status()}) para "${username}": ${text}`)
    }
    const body = await res.json()
    return { token: body.token, user: body.user, ctx }
  }
}

// Context API autenticado (header Authorization: Token ...) para asserts directos.
export async function apiContext(token) {
  return request.newContext({
    baseURL: API_BASE,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: token ? { Authorization: `Token ${token}` } : {},
  })
}

// Token del alumno SIN consumir un login: lo leemos del storageState que dejó
// global-setup (localStorage tymro_token). Lo usan los specs de API (multitenancy,
// rechazos de cupo/solape) para no gatillar el throttle de /login/.
function tokenFromStorage(storagePath, label) {
  if (!fs.existsSync(storagePath)) {
    throw new Error(`Falta ${label} (¿corrió el setup/global-setup?).`)
  }
  const state = JSON.parse(fs.readFileSync(storagePath, 'utf8'))
  const entry = state.origins?.[0]?.localStorage?.find((kv) => kv.name === 'tymro_token')
  if (!entry?.value) {
    throw new Error(`No se encontró tymro_token en ${label}.`)
  }
  return entry.value
}

export function studentTokenFromStorage() {
  return tokenFromStorage(STORAGE_PATH, 'storageState.student.json')
}

// Token del PROFESOR sin consumir un login: lo leemos del storageState que dejó
// su setup (00b-teacher-auth.setup.js). Lo usan los specs de API del profesor
// (multitenancy, pago $0) para no gatillar el throttle de /login/.
export function teacherTokenFromStorage() {
  return tokenFromStorage(TEACHER_STORAGE_PATH, 'storageState.teacher.json')
}

// Datos del profesor (id, organization, branch) leídos del storageState (clave
// 'tymro_user'), útiles para aprovisionar clases sin una query extra.
export function teacherUserFromStorage() {
  if (!fs.existsSync(TEACHER_STORAGE_PATH)) {
    throw new Error('Falta storageState.teacher.json (¿corrió el setup del profesor?).')
  }
  const state = JSON.parse(fs.readFileSync(TEACHER_STORAGE_PATH, 'utf8'))
  const entry = state.origins?.[0]?.localStorage?.find((kv) => kv.name === 'tymro_user')
  if (!entry?.value) {
    throw new Error('No se encontró tymro_user en storageState.teacher.json.')
  }
  return JSON.parse(entry.value)
}
