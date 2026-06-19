import { test, expect } from '@playwright/test'
import { apiContext, getOrgIdBySlug, HOSTS, superadminToken } from './_helpers.js'

const uniq = () => `${Date.now()}${Math.floor(Math.random() * 1e6)}`

test.describe('username ausente en la API', () => {
  let token
  let r2bId

  test.beforeAll(async () => {
    token = await superadminToken()
    r2bId = await getOrgIdBySlug(token, 'r2b-qa')
  })

  test('GET /api/users/?organization_id no expone username', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.get(`users/?organization_id=${r2bId}`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    const list = Array.isArray(data) ? data : data.results || []
    expect(list.length).toBeGreaterThan(0)
    for (const item of list) {
      expect(item).not.toHaveProperty('username')
      expect(item).toHaveProperty('email')
    }
    await ctx.dispose()
  })

  test('GET /api/me/ no expone username', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.get('me/')
    expect(res.status()).toBe(200)
    const me = await res.json()
    expect(me).not.toHaveProperty('username')
    expect(me).toHaveProperty('email')
    await ctx.dispose()
  })

  test('el usuario creado no devuelve username y el email queda', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const email = `oculto-${uniq()}@demo.local`
    const created = await ctx.post('users/', { data: { email, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(created.status()).toBe(201)
    const body = await created.json()
    expect(body).not.toHaveProperty('username')
    expect(body.email).toBe(email)

    const detail = await ctx.get(`users/${body.id}/`)
    expect(detail.status()).toBe(200)
    expect(await detail.json()).not.toHaveProperty('username')
    await ctx.dispose()
  })
})
