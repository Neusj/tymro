import { test as setup, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'

const STORAGE = 'storageState.student.json'

// Este "test" es a la vez la validación del LOGIN VÁLIDO y el establecimiento de la
// sesión del alumno que reutiliza toda la suite. Se hace UNA sola vez porque el
// backend rota el token en cada login (un segundo login mataría esta sesión).
setup('1. Login válido entra al área de alumno (y guarda la sesión)', async ({ page }) => {
  setup.setTimeout(120_000) // holgura si /login está regulado (throttle 5/min)

  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Usuario' }).fill(creds.student.username)
  const throttled = page.getByText(/regulada|throttled/i)

  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.getByRole('textbox', { name: 'Contraseña' }).fill(creds.student.password)
    await page.getByRole('button', { name: 'Entrar' }).click()

    const entered = await page
      .waitForURL(/\/student\/classes\/available/, { timeout: 8000 })
      .then(() => true)
      .catch(() => false)
    if (entered) break

    if (await throttled.isVisible().catch(() => false)) {
      const text = await throttled.innerText()
      const secs = Number((text.match(/(\d+)\s*second/) || [])[1] || 12)
      await page.waitForTimeout((secs + 1) * 1000)
    }
  }

  await expect(page).toHaveURL(/\/student\/classes\/available/)
  await expect(page.getByRole('heading', { name: 'Student · Mis clases' })).toBeVisible()
  await page.context().storageState({ path: STORAGE })
})
