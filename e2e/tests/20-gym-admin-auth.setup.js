import { test as setup, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'

const STORAGE = 'storageState.gym.json'

// Login válido del gym_admin (flujo 1) UNA sola vez: establece la sesión que
// reutiliza toda la suite de gym_admin y guarda el token en storageState.gym.json
// (los specs API leen el token de ahí para no gatillar el throttle de /login/).
// El gym_admin aterriza en /gym-admin/dashboard (utils/roles.js).
setup('Login válido del gym_admin entra al dashboard (y guarda la sesión)', async ({ page }) => {
  setup.setTimeout(120_000) // holgura si /login está regulado (throttle 5/min)

  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Usuario' }).fill(creds.gymAdmin.username)
  const throttled = page.getByText(/regulada|throttled/i)

  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.getByRole('textbox', { name: 'Contraseña' }).fill(creds.gymAdmin.password)
    await page.getByRole('button', { name: 'Entrar' }).click()

    const entered = await page
      .waitForURL(/\/gym-admin\/dashboard/, { timeout: 8000 })
      .then(() => true)
      .catch(() => false)
    if (entered) break

    if (await throttled.isVisible().catch(() => false)) {
      const text = await throttled.innerText()
      const secs = Number((text.match(/(\d+)\s*second/) || [])[1] || 12)
      await page.waitForTimeout((secs + 1) * 1000)
    }
  }

  await expect(page).toHaveURL(/\/gym-admin\/dashboard/)
  await expect(page.getByRole('heading', { name: 'Gym Admin · Dashboard' })).toBeVisible()
  await page.context().storageState({ path: STORAGE })
})
