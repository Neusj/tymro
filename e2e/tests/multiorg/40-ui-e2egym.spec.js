import { test, expect } from '@playwright/test'

// Proyecto e2e-gym: baseURL = http://e2e-gym.localhost:5173. El gym_admin de esta
// org entra a su dashboard (aislado de las otras orgs).
test.describe('UI e2e-gym — gym_admin entra a su dashboard', () => {
  test('gym_admin se loguea por email y entra al dashboard de gym-admin', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('gymadmin@tymro.local')
    await page.locator('input[type="password"]').fill('gymadmin123')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/\/gym-admin\//, { timeout: 20000 })
  })
})
