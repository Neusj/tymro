import { test, expect } from '@playwright/test'
import { openRowAction } from '../fixtures/helpers.js'

// Disciplinas y Tipos de clase: CRUD + rechazo de duplicado case-insensitive.
// (La DataTable renderiza doble → usar .first() para visibilidad.)
test.describe('25. Disciplinas y Tipos de clase (CRUD) gym_admin', () => {
  test('disciplina: crear, duplicado rechazado, eliminar', async ({ page }) => {
    const name = `E2E Disc ${Date.now()}`
    await page.goto('/gym-admin/disciplines')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Disciplinas' })).toBeVisible()
    const main = page.getByRole('main')

    await page.getByRole('button', { name: 'Crear disciplina' }).click()
    let d = page.getByRole('dialog', { name: 'Nueva disciplina' })
    await d.getByRole('textbox').first().fill(name)
    await d.getByRole('button', { name: /Crear|Guardar/ }).click()
    await expect(main.getByText(name, { exact: true }).first()).toBeVisible()

    // Duplicado case-insensitive → 400: NO se crea la variante en mayúsculas.
    await page.getByRole('button', { name: 'Crear disciplina' }).click()
    d = page.getByRole('dialog', { name: 'Nueva disciplina' })
    await d.getByRole('textbox').first().fill(name.toUpperCase())
    await d.getByRole('button', { name: /Crear|Guardar/ }).click()
    await page.waitForTimeout(800)
    await expect(main.getByText(name.toUpperCase(), { exact: true })).toHaveCount(0)
    if (await d.isVisible().catch(() => false)) await d.getByRole('button', { name: 'Cerrar' }).click()

    // Eliminar (dropdown "Abrir acciones").
    await openRowAction(page, new RegExp(name), 'Eliminar')
    await page.getByRole('dialog', { name: 'Eliminar disciplina' }).getByRole('button', { name: 'Eliminar' }).click()
    await expect(main.getByText(name, { exact: true })).toHaveCount(0)
  })

  test('tipo de clase: crear y eliminar', async ({ page }) => {
    const name = `E2E Tipo ${Date.now()}`
    await page.goto('/gym-admin/class-types')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Tipos de Clase' })).toBeVisible()
    const main = page.getByRole('main')

    await page.getByRole('button', { name: 'Crear tipo de clase' }).click()
    const d = page.getByRole('dialog', { name: 'Nuevo tipo de clase' })
    await d.getByRole('textbox').first().fill(name)
    await d.getByRole('button', { name: /Crear|Guardar/ }).click()
    await expect(main.getByText(name, { exact: true }).first()).toBeVisible()

    await openRowAction(page, new RegExp(name), 'Eliminar')
    await page.getByRole('dialog', { name: 'Eliminar tipo' }).getByRole('button', { name: 'Eliminar' }).click()
    await expect(main.getByText(name, { exact: true })).toHaveCount(0)
  })
})
