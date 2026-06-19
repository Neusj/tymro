import { test, expect } from '@playwright/test'
import { fixtures, gymApi } from '../fixtures/gymAdmin.js'

// Aislamiento multi-tenant: el gym_admin de e2e-gym NO puede ver recursos de otra
// organización (la org foránea que siembra el seed). Se manifiesta como 404, no 403.
test.describe('36. Multitenancy gym_admin (API)', () => {
  let api
  let fx

  test.beforeAll(async () => {
    api = await gymApi()
    fx = fixtures()
  })

  test.afterAll(async () => {
    await api?.dispose()
  })

  test('GET de una clase de otra organización → 404', async () => {
    const res = await api.get(`classes/${fx.foreign.class_id}/`)
    expect(res.status()).toBe(404)
  })

  test('el listado de clases NO incluye la org foránea', async () => {
    const res = await api.get('classes/')
    expect(res.ok()).toBeTruthy()
    const data = await res.json()
    const list = Array.isArray(data) ? data : data.results || []
    expect(list.some((c) => c.id === fx.foreign.class_id)).toBeFalsy()
  })

  test('el listado de usuarios NO incluye usuarios de otra org', async () => {
    const res = await api.get('users/')
    expect(res.ok()).toBeTruthy()
    const data = await res.json()
    const list = Array.isArray(data) ? data : data.results || []
    // Todos los usuarios visibles pertenecen al org del gym_admin (e2e-gym).
    expect(list.length).toBeGreaterThan(0)
    expect(list.every((u) => u.organization == null || u.organization === fx.org_id)).toBeTruthy()
  })
})
