import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, studentTokenFromStorage } from '../fixtures/data.js'
import { openRowAction } from '../fixtures/helpers.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

test.describe('5. Recurrencia (serie semanal)', () => {
  test('inscribir, pausar, reactivar y quitar la recurrencia', async ({ page }) => {
    // --- Inscribir (UI) ---
    // Esperamos la respuesta del POST para no navegar antes de que el servidor cree
    // la recurrencia.
    await page.goto('/student/classes/available')
    const [enrollResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/recurring-enroll/') && r.request().method() === 'POST'),
      openRowAction(page, fx.series.name, 'Inscribirme a esta serie semanal'),
    ])
    expect(enrollResp.ok()).toBeTruthy()

    // Aparece como activa en "Mis recurrencias".
    await page.goto('/student/classes/recurring')
    await expect(page.getByRole('heading', { name: 'Student · Mis recurrencias' })).toBeVisible()
    await expect(page.getByRole('row', { name: fx.series.name })).toBeVisible()

    // --- Pausar (UI) ---
    // OJO (comportamiento real del backend): /my-recurring-enrollments filtra
    // is_active=true, así que al pausar la fila DESAPARECE de "Mis recurrencias".
    await openRowAction(page, fx.series.name, 'Pausar recurrencia')
    await expect(page.getByText('Recurrencia pausada.')).toBeVisible()
    await expect(page.getByRole('row', { name: fx.series.name })).toHaveCount(0)

    // --- Reactivar ---
    // Como la pantalla de alumno NO lista las pausadas, su botón "Reactivar" es
    // inalcanzable por UI (limitación de producto). La capacidad SÍ existe en el
    // backend: la ejercemos por API (PATCH is_active=true) y verificamos que vuelve.
    const ctx = await apiContext(studentTokenFromStorage())
    const listRes = await ctx.get(`recurring-enrollments/?class_template=${fx.series.template_id}`)
    const items = await listRes.json()
    const paused = (Array.isArray(items) ? items : items.results || []).find((r) => !r.is_active)
    expect(paused, 'debe existir la recurrencia pausada').toBeTruthy()
    const patch = await ctx.patch(`recurring-enrollments/${paused.id}/`, { data: { is_active: true } })
    expect(patch.ok()).toBeTruthy()
    await ctx.dispose()

    await page.goto('/student/classes/recurring')
    await expect(page.getByRole('row', { name: fx.series.name })).toBeVisible()

    // --- Quitar (UI) --- cancela la recurrencia y sus reservas futuras.
    await openRowAction(page, fx.series.name, 'Quitar recurrencia completa')
    await expect(page.getByText('Recurrencia eliminada')).toBeVisible()
    await expect(page.getByRole('row', { name: fx.series.name })).toHaveCount(0)
  })
})
