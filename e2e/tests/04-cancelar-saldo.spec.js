import { test, expect } from '@playwright/test'
import { loadFixtures } from '../fixtures/data.js'
import { openRowAction, getRemaining } from '../fixtures/helpers.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

test.describe('4. Cancelar una clase', () => {
  test('cancelar una reserva futura devuelve el saldo', async ({ page }) => {
    await page.goto('/student/classes/available')
    await expect(page.getByRole('cell', { name: fx.reservable_b.name, exact: true })).toBeVisible()
    const before = await getRemaining(page)

    // Reservar B (consume 1).
    await openRowAction(page, fx.reservable_b.name, 'Reservar solo esta clase')
    await expect.poll(() => getRemaining(page)).toBe(before - 1)

    // Cancelar B desde "Mis reservas".
    await page.goto('/student/classes/reservations')
    await openRowAction(page, fx.reservable_b.name, 'Cancelar solo esta reserva')
    await expect(page.getByText('Reserva cancelada correctamente')).toBeVisible()

    // Devolución de saldo: vuelve al valor inicial.
    await page.goto('/student/classes/available')
    await expect.poll(() => getRemaining(page)).toBe(before)
  })
})
