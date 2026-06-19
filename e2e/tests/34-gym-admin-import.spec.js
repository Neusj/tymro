import { test, expect } from '@playwright/test'

// Importador XLSX: catálogo de entidades → seleccionar una sin dependencias →
// descargar la plantilla base (paso previo a completar/validar/confirmar).
test.describe('34. Importador de datos gym_admin', () => {
  test('catálogo, seleccionar entidad y descargar plantilla', async ({ page }) => {
    await page.goto('/gym-admin/import')
    await expect(page.getByRole('heading', { name: 'Importar datos' })).toBeVisible()
    const main = page.getByRole('main')

    // Elegir "Disciplinas" (entidad sin dependencias FK).
    await main.getByRole('button', { name: /Disciplinas/ }).first().click()
    const downloadBtn = main.getByRole('button', { name: 'Descargar plantilla base' })
    await expect(downloadBtn).toBeVisible()

    const [dl] = await Promise.all([
      page.waitForEvent('download'),
      downloadBtn.click(),
    ])
    expect(dl.suggestedFilename()).toMatch(/\.xlsx$/i)
  })
})
