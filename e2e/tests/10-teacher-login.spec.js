import { test, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'

// Specs negativos de login del profesor: NO usamos la sesión guardada (storageState
// vacío), igual que 01-login del alumno. El login VÁLIDO ya lo valida el setup
// (00b-teacher-auth.setup.js) al aterrizar en /teacher/classes/upcoming.
test.use({ storageState: { cookies: [], origins: [] } })

test.describe('10. Login del profesor (negativos)', () => {
  test('contraseña inválida → error y permanece en /login', async ({ page }) => {
    test.setTimeout(120_000) // holgura por throttle 5/min

    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Usuario' }).fill(creds.teacher.username)
    await page.getByRole('textbox', { name: 'Contraseña' }).fill('clave-incorrecta-123')
    await page.getByRole('button', { name: 'Entrar' }).click()

    // El front muestra un <p> de error y NO navega fuera de /login.
    await expect(page.locator('form p').filter({ hasText: /.+/ })).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('acceso a ruta de profesor sin sesión → redirige a /login', async ({ page }) => {
    await page.goto('/teacher/classes/upcoming')
    await expect(page).toHaveURL(/\/login/)
  })
})
