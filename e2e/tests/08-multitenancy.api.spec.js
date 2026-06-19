import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, studentTokenFromStorage } from '../fixtures/data.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

test.describe('8. Aislamiento multitenancy', () => {
  test('un alumno no accede a recursos de otra organización', async () => {
    const ctx = await apiContext(studentTokenFromStorage())

    // El detalle de una clase de OTRA org no existe para este alumno → 404.
    const detail = await ctx.get(`classes/${fx.foreign.class_id}/`)
    expect(detail.status(), 'clase foránea debe dar 404').toBe(404)

    // El listado con ?organization_id=<otra> NO escala a la org ajena:
    // el backend ignora el parámetro y filtra por la org del token. Nunca debe
    // aparecer la clase foránea (no hay fuga cross-tenant).
    const list = await ctx.get(`classes/?organization_id=${fx.foreign.org_id}`)
    expect(list.ok()).toBeTruthy()
    const data = await list.json()
    const rows = Array.isArray(data) ? data : (data.results || [])
    expect(rows.some((c) => c.id === fx.foreign.class_id)).toBeFalsy()
    expect(rows.some((c) => c.name === fx.foreign.class_name)).toBeFalsy()

    await ctx.dispose()
  })
})
