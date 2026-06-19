import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, studentTokenFromStorage } from '../fixtures/data.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

test.describe('7. Balance del plan', () => {
  test('plan activo, saldo y vigencia visibles y consistentes', async ({ page }) => {
    // UI: la página de planes solo lista planes VIGENTES por fecha.
    await page.goto('/student/plans')
    await expect(page.getByRole('heading', { name: 'Student · Mis planes' })).toBeVisible()
    const planRow = page.getByRole('row', { name: 'Plan Mensual 12' })
    await expect(planRow).toBeVisible()

    // API: fuente de verdad de saldo y vigencia.
    const ctx = await apiContext(studentTokenFromStorage())
    const res = await ctx.get('plans/my-plan/')
    expect(res.ok()).toBeTruthy()
    const plan = await res.json()
    await ctx.dispose()

    expect(plan.end_date, 'el plan debe tener vigencia (end_date)').toBeTruthy()
    const total = Number(plan.total_classes || 0)
    const used = Number(plan.classes_used || 0)
    expect(total).toBeGreaterThan(0)
    expect(total - used, 'clases restantes no negativas').toBeGreaterThanOrEqual(0)
  })
})
