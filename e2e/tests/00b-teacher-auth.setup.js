import { test as setup, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'

const STORAGE = 'storageState.teacher.json'

// Igual que el alumno: este "test" valida el LOGIN VÁLIDO del profesor (flujo 1) y
// establece la sesión que reutiliza toda la suite del profesor. UNA sola vez porque
// el backend rota el token en cada login (un segundo login mataría esta sesión).
// El profesor aterriza en /teacher/classes/upcoming (utils/roles.js).
setup('1. Login válido del profesor entra a sus clases (y guarda la sesión)', async ({ page }) => {
  setup.setTimeout(120_000) // holgura si /login está regulado (throttle 5/min)

  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Usuario' }).fill(creds.teacher.username)
  const throttled = page.getByText(/regulada|throttled/i)

  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.getByRole('textbox', { name: 'Contraseña' }).fill(creds.teacher.password)
    await page.getByRole('button', { name: 'Entrar' }).click()

    const entered = await page
      .waitForURL(/\/teacher\/classes\/upcoming/, { timeout: 8000 })
      .then(() => true)
      .catch(() => false)
    if (entered) break

    if (await throttled.isVisible().catch(() => false)) {
      const text = await throttled.innerText()
      const secs = Number((text.match(/(\d+)\s*second/) || [])[1] || 12)
      await page.waitForTimeout((secs + 1) * 1000)
    }
  }

  await expect(page).toHaveURL(/\/teacher\/classes\/upcoming/)
  await expect(page.getByRole('heading', { name: 'Teacher · Proximas clases' })).toBeVisible()
  await page.context().storageState({ path: STORAGE })
})
