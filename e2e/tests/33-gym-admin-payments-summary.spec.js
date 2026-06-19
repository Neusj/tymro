import { test, expect } from '@playwright/test'

// Resumen de pagos a profesores: total del período, profesores, y export CSV/XLSX.
test.describe('33. Resumen de pagos a profesores gym_admin', () => {
  test('muestra total del período y los profesores con pago', async ({ page }) => {
    await page.goto('/gym-admin/teacher-payments')
    await expect(page.getByRole('heading', { name: 'Pagos Profesores · Resumen' })).toBeVisible()
    const main = page.getByRole('main')
    await expect(main.getByText(/Total a pagar/)).toBeVisible()
    // Profesores del cálculo sembrado en el período actual.
    await expect(main.getByText('ProfeFijo Pago').first()).toBeVisible()
  })

  test('exporta CSV y XLSX', async ({ page }) => {
    await page.goto('/gym-admin/teacher-payments')
    const main = page.getByRole('main')
    await expect(main.getByRole('button', { name: 'CSV' })).toBeEnabled()

    const [csv] = await Promise.all([
      page.waitForEvent('download'),
      main.getByRole('button', { name: 'CSV' }).click(),
    ])
    expect(csv.suggestedFilename()).toMatch(/\.csv$/i)

    const [xlsx] = await Promise.all([
      page.waitForEvent('download'),
      main.getByRole('button', { name: 'Excel' }).click(),
    ])
    expect(xlsx.suggestedFilename()).toMatch(/\.xlsx$/i)
  })
})
