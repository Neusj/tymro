import { test, expect } from '@playwright/test'

// Proyecto superadmin: baseURL = apex (http://localhost:5173). Login propio por
// navegador (no depende de storageState, robusto ante la rotación de token).
test.describe('UI superadmin (apex) — login por email', () => {
  test('la página de login pide Email (no Usuario/Username)', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('input[type="email"]')).toBeVisible()
    await expect(page.getByText('Email', { exact: true })).toBeVisible()
    await expect(page.getByText(/Usuario|Username/)).toHaveCount(0)
  })

  test('superadmin se loguea por email y entra a Organizaciones', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('superadmin@tymro.local')
    await page.locator('input[type="password"]').fill('superadmin123')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/\/superadmin\/organizations/, { timeout: 20000 })
  })

  test('credenciales inválidas muestran error y NO entran', async ({ page }) => {
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('superadmin@tymro.local')
    await page.locator('input[type="password"]').fill('clave-mala')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/\/login/)
  })
})
