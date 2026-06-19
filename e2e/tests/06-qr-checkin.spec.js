import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext } from '../fixtures/data.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

test.describe('6. QR check-in', () => {
  test('marcar asistencia con un token QR vivo (sin cámara)', async ({ page }) => {
    // 1) El gym_admin pide el QR vigente (el token rota ~10s).
    const admin = await apiContext(fx.tokens.gymAdmin)
    const res = await admin.get('attendance-qr/current/')
    expect(res.ok()).toBeTruthy()
    const { check_in_path } = await res.json()
    await admin.dispose()
    expect(check_in_path).toContain('/attendance/check-in?token=')

    // 2) El alumno abre el link del QR (lo que haría su cámara) y marca asistencia.
    await page.goto(check_in_path)
    await expect(page.getByText(fx.live_class_name)).toBeVisible()
    await page.getByRole('button', { name: 'Marcar asistencia' }).click()

    await expect(page.getByText('Tu asistencia fue registrada correctamente.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Asistencia registrada' })).toBeVisible()
  })
})
