import { test, expect } from '@playwright/test'

// La DataTable renderiza doble (tabla escritorio + cards móvil): el texto aparece
// 2× en el DOM. Usamos .first() para visibilidad y conteo por delta para duplicados.
async function deleteRow(page, name) {
  const row = page.getByRole('row', { name: new RegExp(name) }).first()
  const opener = row.getByRole('button', { name: 'Abrir acciones' })
  if (await opener.count()) {
    await opener.click()
    await page.getByRole('button', { name: 'Eliminar', exact: true }).click()
  } else {
    await row.getByRole('button', { name: 'Eliminar' }).click()
  }
}

test.describe('26. Sucursales (CRUD) gym_admin', () => {
  test('crear, rechazar duplicado y eliminar', async ({ page }) => {
    const name = `E2E Sucursal ${Date.now()}`
    await page.goto('/gym-admin/branches')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Sucursales' })).toBeVisible()
    const cell = page.getByRole('main').getByText(name, { exact: true })

    await page.getByRole('button', { name: 'Nueva sucursal' }).click()
    let dialog = page.getByRole('dialog', { name: 'Nueva sucursal' })
    await dialog.getByRole('textbox').first().fill(name)
    await dialog.getByRole('button', { name: 'Guardar' }).click()
    await expect(cell.first()).toBeVisible()
    const created = await cell.count()

    // Duplicado: el backend rechaza (400); no se crea una fila más.
    await page.getByRole('button', { name: 'Nueva sucursal' }).click()
    dialog = page.getByRole('dialog', { name: 'Nueva sucursal' })
    await dialog.getByRole('textbox').first().fill(name)
    await dialog.getByRole('button', { name: 'Guardar' }).click()
    await page.waitForTimeout(800)
    await expect(cell).toHaveCount(created)
    if (await dialog.isVisible().catch(() => false)) {
      await dialog.getByRole('button', { name: 'Cerrar' }).click()
    }

    // Eliminar.
    await deleteRow(page, name)
    await page.getByRole('dialog', { name: 'Eliminar sucursal' }).getByRole('button', { name: 'Eliminar' }).click()
    await expect(cell).toHaveCount(0)
  })
})
