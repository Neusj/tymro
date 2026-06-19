import { test, expect } from '@playwright/test'

// Festivos: crear un festivo manual (ámbito organización) y verlo en la lista.
// Los festivos activos bloquean la generación de clases (cubierto por seed/pytest).
test.describe('28. Festivos gym_admin', () => {
  test('crear festivo manual', async ({ page }) => {
    const name = `E2E Feriado ${Date.now()}`
    const date = '2031-12-25'
    await page.goto('/gym-admin/holidays')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Festivos' })).toBeVisible()
    const main = page.getByRole('main')

    await main.getByLabel('Fecha').fill(date)
    await main.getByLabel('Nombre').fill(name)
    await main.getByRole('button', { name: 'Crear festivo' }).click()
    await expect(main.getByText(name, { exact: true }).first()).toBeVisible()
  })
})
