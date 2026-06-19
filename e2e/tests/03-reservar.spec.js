import { test, expect } from '@playwright/test'
import { loadFixtures } from '../fixtures/data.js'
import { openRowAction, getRemaining } from '../fixtures/helpers.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

test.describe('3. Reservar una clase', () => {
  test('reserva una clase, aparece en Mis reservas y descuenta saldo', async ({ page }) => {
    await page.goto('/student/classes/available')
    // Esperar a que la tabla (y el plan) carguen: el badge muestra "0 clases"
    // transitoriamente hasta que /plans/my-plan/ resuelve.
    await expect(page.getByRole('cell', { name: fx.reservable_a.name, exact: true })).toBeVisible()
    const before = await getRemaining(page)

    await openRowAction(page, fx.reservable_a.name, 'Reservar solo esta clase')

    // El saldo baja en 1 y la clase deja de estar "disponible".
    await expect.poll(() => getRemaining(page)).toBe(before - 1)
    await expect(page.getByRole('cell', { name: fx.reservable_a.name, exact: true })).toHaveCount(0)

    // Aparece como reserva activa en "Mis reservas".
    await page.goto('/student/classes/reservations')
    const row = page.getByRole('row', { name: fx.reservable_a.name })
    await expect(row).toBeVisible()
    await expect(row.getByText('Activa', { exact: true })).toBeVisible()

    // Limpieza: cancelar para restaurar el saldo base de la suite.
    await openRowAction(page, fx.reservable_a.name, 'Cancelar solo esta reserva')
    await expect(page.getByText('Reserva cancelada correctamente')).toBeVisible()
  })
})
