import { test, expect } from '@playwright/test'
import { apiContext, HOSTS } from './_helpers.js'

// El reset es por email y se acota a la org del subdominio. Responde SIEMPRE 200
// (anti-enumeración), exista o no el email.
test.describe('Password reset scoped por organización', () => {
  test('reset para email existente en r2b-qa -> 200', async () => {
    const ctx = await apiContext({ host: HOSTS.r2b })
    const res = await ctx.post('password-reset/', { data: { email: 'student1@tymro.local' } })
    expect(res.status()).toBe(200)
    await ctx.dispose()
  })

  test('reset para email inexistente -> 200 (anti-enumeración)', async () => {
    const ctx = await apiContext({ host: HOSTS.r2b })
    const res = await ctx.post('password-reset/', { data: { email: 'no-existe@demo.local' } })
    expect(res.status()).toBe(200)
    await ctx.dispose()
  })

  test('reset en gym-test para su gym_admin -> 200', async () => {
    const ctx = await apiContext({ host: HOSTS.gymTest })
    const res = await ctx.post('password-reset/', { data: { email: 'gymadmin@tymro.local' } })
    expect(res.status()).toBe(200)
    await ctx.dispose()
  })
})
