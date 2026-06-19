import { test, expect } from '@playwright/test'

// Proyecto gym-test: baseURL = http://gym-test.localhost:5173 (Chromium resuelve
// *.localhost). Demuestra que el MISMO email (juan@demo.local) en este subdominio
// entra como PROFESOR (en r2b-qa es alumno).
test.describe('UI gym-test — email compartido entra como profesor', () => {
  test('juan@demo.local se loguea y entra al área de profesor', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('juan@demo.local')
    await page.locator('input[type="password"]').fill('teacher123')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/\/teacher\//, { timeout: 20000 })
  })

  test('la clave de alumno (r2b) NO sirve para juan en gym-test', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('juan@demo.local')
    await page.locator('input[type="password"]').fill('student123')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/\/login/)
  })
})
