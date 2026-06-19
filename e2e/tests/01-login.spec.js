import { test, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'

// El login VÁLIDO se prueba en 00-auth.setup.js (además, establece la sesión).
// Aquí solo el caso negativo, partiendo SIN sesión.
test.use({ storageState: { cookies: [], origins: [] } })

test.describe('1. Login (rechazo)', () => {
  // Holgura por si /login está temporalmente regulado (throttle 5/min): reintentamos.
  test.setTimeout(120_000)

  test('credenciales inválidas → error claro, sin entrar', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Usuario' }).fill(creds.student.username)
    const password = page.getByRole('textbox', { name: 'Contraseña' })
    const invalid = page.getByText('Credenciales inválidas.')
    const throttled = page.getByText(/regulada|throttled/i)

    for (let attempt = 0; attempt < 4; attempt += 1) {
      await password.fill('clave-incorrecta')
      await page.getByRole('button', { name: 'Entrar' }).click()
      await expect(invalid.or(throttled)).toBeVisible()
      if (await invalid.isVisible()) break
      // /login está regulado (throttle): esperamos el backoff exacto y reintentamos.
      const text = await throttled.innerText()
      const secs = Number((text.match(/(\d+)\s*second/) || [])[1] || 12)
      await page.waitForTimeout((secs + 1) * 1000)
    }

    await expect(invalid).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })
})
