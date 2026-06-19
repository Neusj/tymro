import { test, expect } from '@playwright/test'
import { openRowAction } from '../fixtures/helpers.js'

// Festivos: crear (manual, ámbito organización) y eliminar. Los festivos activos
// bloquean la generación de clases (validado a nivel de seed/recurrencia y pytest).
test.describe('28. Festivos (CRUD) gym_admin', () => {
  test('crear festivo manual y eliminarlo', async ({ page }) => {
    const name = `E2E Feriado ${Date.now()}`
    const date = '2031-12-25'
    page.on('dialog', (dialog) => dialog.accept()) // el borrado usa window.confirm

    await page.goto('/gym-admin/holidays')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Festivos' })).toBeVisible()
    const main = page.getByRole('main')

    await main.getByLabel('Fecha').fill(date)
    await main.getByLabel('Nombre').fill(name)
    await main.getByRole('button', { name: 'Crear festivo' }).click()
    await expect(main.getByText(name, { exact: true }).first()).toBeVisible()

    await openRowAction(page, new RegExp(name), 'Eliminar')
    await expect(main.getByText(name, { exact: true })).toHaveCount(0)
  })
})
