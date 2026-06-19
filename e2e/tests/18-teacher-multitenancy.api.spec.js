import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage } from '../fixtures/data.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
test.beforeAll(() => {
  fx = loadFixtures()
})

test.describe('18. Aislamiento multitenancy (profesor)', () => {
  test('el profesor no ve una clase de otra organización (404 en el detalle)', async ({ page }) => {
    const ctx = await apiContext(teacherTokenFromStorage())
    const detail = await ctx.get(`classes/${fx.foreign.class_id}/`)
    // El recurso "no existe" para este profesor → 404 (la existencia queda oculta), no 403.
    expect(detail.status(), 'clase foránea debe dar 404').toBe(404)
    await ctx.dispose()
  })

  test('el listado no filtra a otra org aunque se inyecte organization_id', async ({ page }) => {
    const ctx = await apiContext(teacherTokenFromStorage())
    const list = await ctx.get(`classes/?organization_id=${fx.foreign.org_id}`)
    expect(list.ok()).toBeTruthy()
    const data = await list.json()
    const rows = Array.isArray(data) ? data : data.results || []
    expect(rows.some((c) => c.id === fx.foreign.class_id), 'no debe filtrarse la clase foránea').toBeFalsy()
    expect(rows.some((c) => c.name === fx.foreign.class_name), 'no debe filtrarse por nombre').toBeFalsy()
    await ctx.dispose()
  })

  test('una acción del profesor sobre clase ajena → 404', async ({ page }) => {
    const ctx = await apiContext(teacherTokenFromStorage())
    const res = await ctx.post(`classes/${fx.foreign.class_id}/suspend/`, { data: { suspend_reason: 'x' } })
    expect([403, 404], 'acción cross-tenant bloqueada').toContain(res.status())
    await ctx.dispose()
  })
})
