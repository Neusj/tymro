import { test, expect } from '@playwright/test'
import { apiContext, getOrgIdBySlug, HOSTS, superadminToken } from './_helpers.js'

const uniq = () => `${Date.now()}${Math.floor(Math.random() * 1e6)}`

test.describe('Unicidad de email POR organización', () => {
  let token
  let r2bId
  let gymTestId

  test.beforeAll(async () => {
    token = await superadminToken()
    r2bId = await getOrgIdBySlug(token, 'r2b-qa')
    gymTestId = await getOrgIdBySlug(token, 'gym-test')
    expect(r2bId).toBeTruthy()
    expect(gymTestId).toBeTruthy()
  })

  test('el mismo email se puede crear en DOS orgs distintas', async () => {
    const email = `compartido-${uniq()}@demo.local`
    const ctx = await apiContext({ host: HOSTS.apex, token })

    const a = await ctx.post('users/', { data: { email, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(a.status(), JSON.stringify(await a.json())).toBe(201)

    const b = await ctx.post('users/', { data: { email, role: 'teacher', password: 'Passw0rd2026', organization: gymTestId } })
    expect(b.status(), JSON.stringify(await b.json())).toBe(201)

    await ctx.dispose()
  })

  test('email duplicado en la MISMA org -> 400', async () => {
    const email = `dup-${uniq()}@demo.local`
    const ctx = await apiContext({ host: HOSTS.apex, token })

    const first = await ctx.post('users/', { data: { email, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(first.status()).toBe(201)

    const second = await ctx.post('users/', { data: { email, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(second.status()).toBe(400)
    expect(await second.json()).toHaveProperty('email')

    await ctx.dispose()
  })

  test('email duplicado case-insensitive en la misma org -> 400', async () => {
    const base = `caso-${uniq()}@demo.local`
    const ctx = await apiContext({ host: HOSTS.apex, token })

    const first = await ctx.post('users/', { data: { email: base, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(first.status()).toBe(201)

    const upper = base.toUpperCase()
    const second = await ctx.post('users/', { data: { email: upper, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(second.status()).toBe(400)

    await ctx.dispose()
  })

  test('email obligatorio al crear usuario', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.post('users/', { data: { role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    expect(res.status()).toBe(400)
    expect(await res.json()).toHaveProperty('email')
    await ctx.dispose()
  })
})
