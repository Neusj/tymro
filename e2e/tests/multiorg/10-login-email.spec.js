import { test, expect } from '@playwright/test'
import { apiLogin, CREDS, HOSTS } from './_helpers.js'

// Login por EMAIL, desambiguado por el subdominio (X-Forwarded-Host).
test.describe('Login por email + subdominio', () => {
  test('r2b-qa: alumno entra con su email', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.r2b, ...CREDS.r2bStudent })
    expect(status).toBe(200)
    expect(body.role).toBe('student')
    expect(body.token).toBeTruthy()
  })

  test('r2b-qa: gym_admin entra con su email', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.r2b, ...CREDS.r2bGymAdmin })
    expect(status).toBe(200)
    expect(body.role).toBe('gym_admin')
  })

  test('gym-test: gym_admin entra con su email', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.gymTest, ...CREDS.gymTestGymAdmin })
    expect(status).toBe(200)
    expect(body.role).toBe('gym_admin')
  })

  test('e2e-gym: gym_admin entra con su email', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.e2eGym, ...CREDS.e2eGymAdmin })
    expect(status).toBe(200)
    expect(body.role).toBe('gym_admin')
  })

  test('superadmin entra en el apex', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.apex, ...CREDS.superadmin })
    expect(status).toBe(200)
    expect(body.role).toBe('superadmin')
    expect(body.organization).toBeNull()
  })

  test('email compartido juan@demo.local: en r2b-qa es ALUMNO', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.r2b, ...CREDS.sharedR2bStudent })
    expect(status).toBe(200)
    expect(body.role).toBe('student')
  })

  test('email compartido juan@demo.local: en gym-test es PROFESOR', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.gymTest, ...CREDS.sharedGymTestTeacher })
    expect(status).toBe(200)
    expect(body.role).toBe('teacher')
  })

  test('email compartido: org distinta en cada subdominio', async () => {
    const a = await apiLogin({ host: HOSTS.r2b, ...CREDS.sharedR2bStudent })
    const b = await apiLogin({ host: HOSTS.gymTest, ...CREDS.sharedGymTestTeacher })
    expect(a.status).toBe(200)
    expect(b.status).toBe(200)
    expect(a.body.organization).not.toBe(b.body.organization)
  })

  test('password incorrecto -> 400', async () => {
    const { status } = await apiLogin({ host: HOSTS.r2b, email: CREDS.r2bStudent.email, password: 'malisima' })
    expect(status).toBe(400)
  })

  test('falta password -> 400', async () => {
    const { status } = await apiLogin({ host: HOSTS.r2b, email: CREDS.r2bStudent.email, password: '' })
    expect(status).toBe(400)
  })

  test('superadmin NO entra desde un subdominio de org (su email no existe en esa org)', async () => {
    const { status } = await apiLogin({ host: HOSTS.r2b, ...CREDS.superadmin })
    expect(status).toBe(400)
  })

  test('la clave de juan en r2b (student123) NO sirve en gym-test', async () => {
    // juan@demo.local existe en AMBAS orgs, pero con clave distinta: en gym-test es
    // profesor (teacher123). La clave de r2b no valida en gym-test → aislamiento.
    const { status } = await apiLogin({ host: HOSTS.gymTest, email: 'juan@demo.local', password: 'student123' })
    expect(status).toBe(400)
  })
})
