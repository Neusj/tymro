import { test, expect } from '@playwright/test'

// Clases: crear una clase puntual. Al crear OK, la página redirige a /gym-admin/classes.
test.describe('27. Clases gym_admin', () => {
  test('crear clase puntual', async ({ page }) => {
    const name = `E2E Clase ${Date.now()}`
    await page.goto('/gym-admin/classes/create')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Crear Clase' })).toBeVisible()
    const main = page.getByRole('main')

    await main.getByLabel('Nombre').fill(name)
    await main.getByLabel('Sucursal').selectOption({ index: 1 })
    await main.getByLabel('Profesor').selectOption({ index: 1 })
    await main.getByLabel('Tipo').selectOption({ index: 1 })
    await main.getByLabel('Disciplina').selectOption({ index: 1 })
    await main.getByLabel('Inicio').fill('2026-07-01T10:00')
    await main.getByLabel('Término').fill('2026-07-01T11:00')
    await main.getByLabel('Cupos').fill('10')
    await main.getByRole('button', { name: 'Crear clase' }).click()

    // Crear OK → navigate('/gym-admin/classes').
    await expect(page).toHaveURL(/\/gym-admin\/classes$/)
  })
})
