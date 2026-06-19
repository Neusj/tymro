import { test, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'

// El login VÁLIDO ya lo prueba 20-gym-admin-auth.setup.js (aterriza en el dashboard
// y guarda la sesión). Aquí: que la sesión válida llega al dashboard, y los negativos.
test.describe('21. Auth gym_admin (con sesión)', () => {
  test('la sesión válida aterriza en el dashboard', async ({ page }) => {
    await page.goto('/gym-admin/dashboard')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Dashboard' })).toBeVisible()
  })
})

test.describe('21. Auth gym_admin (sin sesión)', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('credenciales inválidas → error y permanece en /login', async ({ page }) => {
    test.setTimeout(120_000) // holgura por throttle 5/min

    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Usuario' }).fill(creds.gymAdmin.username)
    await page.getByRole('textbox', { name: 'Contraseña' }).fill('clave-incorrecta-123')
    await page.getByRole('button', { name: 'Entrar' }).click()

    // Muestra un <p> de error (credenciales inválidas o throttle) y no navega.
    await expect(page.locator('form p').filter({ hasText: /.+/ })).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('ruta de gym-admin sin sesión → redirige a /login', async ({ page }) => {
    await page.goto('/gym-admin/users')
    await expect(page).toHaveURL(/\/login/)
  })
})
