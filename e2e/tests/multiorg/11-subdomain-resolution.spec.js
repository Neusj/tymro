import { test, expect } from '@playwright/test'
import { apiContext, apiLogin, HOSTS } from './_helpers.js'

// El subdominio del Host resuelve la org; uno inexistente da 404.
test.describe('Resolución de organización por subdominio', () => {
  test('subdominio inexistente -> 404 en login', async () => {
    const { status } = await apiLogin({ host: HOSTS.unknown, email: 'x@x.com', password: 'y' })
    expect(status).toBe(404)
  })

  test('subdominio inexistente -> 404 en /users/', async () => {
    const ctx = await apiContext({ host: HOSTS.unknown })
    const res = await ctx.get('users/')
    await ctx.dispose()
    expect(res.status()).toBe(404)
  })

  test('/health/ está en allowlist (200 aun en subdominio inexistente)', async () => {
    const ctx = await apiContext({ host: HOSTS.unknown })
    const res = await ctx.get('health/')
    await ctx.dispose()
    expect(res.status()).toBe(200)
  })

  test('apex resuelve contexto plataforma (login superadmin ok)', async () => {
    const { status, body } = await apiLogin({ host: HOSTS.apex, email: 'superadmin@tymro.local', password: 'superadmin123' })
    expect(status).toBe(200)
    expect(body.organization).toBeNull()
  })

  test('subdominio válido (r2b-qa) resuelve (login da 400 cred inválidas, no 404)', async () => {
    const { status } = await apiLogin({ host: HOSTS.r2b, email: 'nadie@r2b.local', password: 'x' })
    expect(status).toBe(400)
  })
})
