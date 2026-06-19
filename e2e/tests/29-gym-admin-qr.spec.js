import { test, expect } from '@playwright/test'

// QR de asistencia: el QR rotante se renderiza y el código permanente se regenera.
test.describe('29. QR de asistencia gym_admin', () => {
  test('muestra el QR rotante', async ({ page }) => {
    await page.goto('/gym-admin/attendance-qr')
    await expect(page.getByRole('heading', { name: 'QR de asistencia' })).toBeVisible()
    await expect(page.getByRole('img', { name: 'QR de asistencia' })).toBeVisible()
  })

  test('regenera el código permanente', async ({ page }) => {
    await page.goto('/gym-admin/attendance-qr')
    const main = page.getByRole('main')
    await main.getByRole('button', { name: 'Regenerar permanente' }).click()
    await expect(main.getByText('Codigo permanente regenerado.')).toBeVisible()
  })
})
