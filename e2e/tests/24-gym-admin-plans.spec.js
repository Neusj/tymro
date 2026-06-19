import { test, expect } from '@playwright/test'
import { openRowAction } from '../fixtures/helpers.js'

// Planes: listado muestra planes sembrados, y CRUD (crear mensual + eliminar).
test.describe('24. Planes (CRUD) gym_admin', () => {
  test('listado muestra planes sembrados', async ({ page }) => {
    await page.goto('/gym-admin/plans')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Planes' })).toBeVisible()
    // El seed de e2e-gym crea el plan de cálculo "E2E Pago A 4/40k".
    await expect(page.getByRole('main').getByText('E2E Pago A 4/40k', { exact: true }).first()).toBeVisible()
  })

  test('crear plan mensual y eliminarlo', async ({ page }) => {
    const name = `E2E Plan ${Date.now()}`
    await page.goto('/gym-admin/plans')
    const main = page.getByRole('main')

    await page.getByRole('button', { name: 'Crear plan' }).click()
    const d = page.getByRole('dialog', { name: 'Crear plan' })
    await d.getByRole('textbox').first().fill(name) // Nombre (único textbox de texto)
    await d.getByLabel('Clases totales').fill('12')
    await d.getByLabel('Duración (días)').fill('30')
    await d.getByLabel('Precio').fill('30000')
    await d.getByRole('button', { name: 'Guardar' }).click()
    await expect(main.getByText(name, { exact: true }).first()).toBeVisible()

    // Acciones del plan (3) → DataTable las colapsa en el dropdown "Abrir acciones".
    const row = page.getByRole('row', { name: new RegExp(name) }).first()
    const opener = row.getByRole('button', { name: 'Abrir acciones' })
    if (await opener.count()) await opener.click()
    await page.getByRole('button', { name: 'Eliminar', exact: true }).filter({ visible: true }).first().click()
    await page.getByRole('dialog', { name: 'Eliminar plan' }).getByRole('button', { name: /Eliminar|Confirmar/ }).click()
    await expect(main.getByText(name, { exact: true })).toHaveCount(0)
  })
})
