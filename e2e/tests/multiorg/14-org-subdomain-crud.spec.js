import { test, expect } from '@playwright/test'
import { apiContext, apiLogin, HOSTS, superadminToken } from './_helpers.js'

const uniq = () => `${Date.now()}${Math.floor(Math.random() * 1e6)}`

test.describe('Crear organización con subdominio', () => {
  let token

  test.beforeAll(async () => {
    token = await superadminToken()
  })

  test('superadmin crea org con subdominio (201) y el subdominio mapea', async () => {
    const sub = `new-gym-${uniq()}`
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.post('organizations/', { data: { name: 'New Gym', slug: sub, subdomain: sub } })
    expect(res.status(), JSON.stringify(await res.json())).toBe(201)
    expect((await res.json()).subdomain).toBe(sub)
    await ctx.dispose()

    // El subdominio recién creado RESUELVE: login da 400 (cred inválidas), no 404.
    const login = await apiLogin({ host: `${sub}.localhost`, email: 'nadie@x.com', password: 'x' })
    expect(login.status).toBe(400)
  })

  test('subdominio reservado (admin) -> 400', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.post('organizations/', { data: { name: 'X', slug: `x-${uniq()}`, subdomain: 'admin' } })
    expect(res.status()).toBe(400)
    expect(await res.json()).toHaveProperty('subdomain')
    await ctx.dispose()
  })

  test('subdominio obligatorio al crear -> 400', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.post('organizations/', { data: { name: 'X', slug: `x-${uniq()}` } })
    expect(res.status()).toBe(400)
    expect(await res.json()).toHaveProperty('subdomain')
    await ctx.dispose()
  })

  test('subdominio duplicado (r2b-qa) -> 400', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.post('organizations/', { data: { name: 'X', slug: `x-${uniq()}`, subdomain: 'r2b-qa' } })
    expect(res.status()).toBe(400)
    await ctx.dispose()
  })

  test('subdominio con formato inválido (mayúsculas/espacios) -> 400', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.post('organizations/', { data: { name: 'X', slug: `x-${uniq()}`, subdomain: 'Mal Subdominio' } })
    expect(res.status()).toBe(400)
    await ctx.dispose()
  })

  test('un gym_admin NO puede crear organizaciones (403)', async () => {
    const { token: gymToken } = await apiLogin({ host: HOSTS.r2b, email: 'gymadmin@tymro.local', password: 'gymadmin123' })
    const ctx = await apiContext({ host: HOSTS.r2b, token: gymToken })
    const res = await ctx.post('organizations/', { data: { name: 'X', slug: `x-${uniq()}`, subdomain: `x-${uniq()}` } })
    expect(res.status()).toBe(403)
    await ctx.dispose()
  })
})
