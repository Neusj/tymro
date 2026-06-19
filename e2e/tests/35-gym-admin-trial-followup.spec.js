import { test, expect } from '@playwright/test'

// Trial-followup: editar la config del email de seguimiento + casos negativos.
test.describe('35. Trial-followup (config emails) gym_admin', () => {
  const OK = 'Configuración guardada correctamente.'

  test('editar y guardar la configuración', async ({ page }) => {
    await page.goto('/gym-admin/settings/trial-followup')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Configuraciones' })).toBeVisible()
    const main = page.getByRole('main')

    await main.getByLabel('Asunto del email').fill(`Bienvenido ${Date.now()}`)
    await main.getByLabel('Cuerpo del email').fill('Hola {student_name}, te esperamos en {org_name}.')
    await main.getByLabel('Delay en minutos tras el fin de la clase').fill('45')
    await main.getByRole('button', { name: 'Guardar' }).click()

    await expect(main.getByText(OK)).toBeVisible()
  })

  test('asunto vacío → error de validación (no guarda)', async ({ page }) => {
    await page.goto('/gym-admin/settings/trial-followup')
    const main = page.getByRole('main')
    await expect(main.getByLabel('Asunto del email')).toBeVisible()

    await main.getByLabel('Asunto del email').fill('')
    await main.getByLabel('Cuerpo del email').fill('algo')
    await main.getByRole('button', { name: 'Guardar' }).click()

    await page.waitForTimeout(800)
    await expect(main.getByText(OK)).toHaveCount(0) // no muestra éxito
  })
})
