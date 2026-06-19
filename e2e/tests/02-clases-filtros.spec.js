import { test, expect } from '@playwright/test'
import { loadFixtures } from '../fixtures/data.js'
import { selectFilter } from '../fixtures/helpers.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

const cell = (page, name) => page.getByRole('cell', { name, exact: true })

test.describe('2. Clases disponibles y filtros', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/student/classes/available')
    await expect(page.getByRole('heading', { name: 'Clases disponibles' })).toBeVisible()
  })

  test('la lista muestra las clases sembradas', async ({ page }) => {
    await expect(cell(page, fx.reservable_a.name)).toBeVisible()
    await expect(cell(page, fx.yoga_class.name)).toBeVisible()
  })

  test('filtro por Disciplina discrimina', async ({ page }) => {
    await selectFilter(page, 'Disciplina', fx.filters.discipline_alt) // Yoga
    await expect(cell(page, fx.yoga_class.name)).toBeVisible()
    await expect(cell(page, fx.reservable_a.name)).toHaveCount(0)

    await selectFilter(page, 'Disciplina', fx.filters.discipline_main) // Funcional
    await expect(cell(page, fx.reservable_a.name)).toBeVisible()
    await expect(cell(page, fx.yoga_class.name)).toHaveCount(0)
  })

  test('filtro por Profesor discrimina', async ({ page }) => {
    await selectFilter(page, 'Profesor', fx.filters.teacher_alt) // Pedro Leiva
    await expect(cell(page, fx.yoga_class.name)).toBeVisible()
    await expect(cell(page, fx.reservable_a.name)).toHaveCount(0)
  })

  test('filtro por Estado discrimina (Cancelada → sin programadas)', async ({ page }) => {
    await selectFilter(page, 'Estado', 'Cancelada')
    await expect(cell(page, fx.reservable_a.name)).toHaveCount(0)
    await selectFilter(page, 'Estado', 'Programada')
    await expect(cell(page, fx.reservable_a.name)).toBeVisible()
  })

  test('filtro por fecha "Semana" oculta clases lejanas', async ({ page }) => {
    // Los fixtures están a +9..+14 días → fuera de la ventana de 7 días.
    await page.getByRole('button', { name: 'Semana', exact: true }).click()
    await expect(cell(page, fx.reservable_a.name)).toHaveCount(0)
  })
})
