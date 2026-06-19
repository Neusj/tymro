import { test, expect } from '@playwright/test'

// Dashboard gym_admin: 4 KPIs reales scopeados a la org, navegables.
test.describe('22. Dashboard gym_admin', () => {
  test('muestra heading y los 4 KPIs con valor numérico', async ({ page }) => {
    await page.goto('/gym-admin/dashboard')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Dashboard' })).toBeVisible()

    const main = page.getByRole('main')
    for (const title of ['Sucursales', 'Profesores', 'Alumnos', 'Usuarios']) {
      const card = main.getByRole('link', { name: new RegExp(title) })
      await expect(card).toBeVisible()
      await expect(card).toContainText(/\d/) // StatCard muestra un valor numérico
    }
  })

  test('el StatCard de Sucursales navega a /gym-admin/branches', async ({ page }) => {
    await page.goto('/gym-admin/dashboard')
    await page.getByRole('main').getByRole('link', { name: /Sucursales/ }).first().click()
    await expect(page).toHaveURL(/\/gym-admin\/branches/)
  })
})
