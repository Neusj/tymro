import { test, expect } from '@playwright/test'

// Reglas de pago: crear las DOS opciones porcentuales (por asistencia / por reserva)
// desde el dropdown nuevo. Valida la feature + el fix del serializer end-to-end.
test.describe('31. Reglas de pago a profesor gym_admin', () => {
  async function createPctRule(page, base, pct) {
    await page.goto('/gym-admin/teacher-payments/rules')
    await expect(page.getByRole('heading', { name: 'Pagos Profesores - Reglas' })).toBeVisible()
    await page.getByRole('button', { name: 'Nueva regla' }).click()
    const d = page.getByRole('dialog')
    await d.getByLabel('Tipo de pago').selectOption('per_plan_price')
    await d.getByLabel(/Sobre quién/).selectOption(base)
    await d.getByLabel(/Porcentaje/).fill(String(pct))
    await d.getByRole('button', { name: 'Guardar' }).click()
    await expect(page.getByRole('main').getByText('Regla creada.')).toBeVisible()
  }

  test('crear regla POR ASISTENCIA (per_plan_price + present_attendees, 40%)', async ({ page }) => {
    await createPctRule(page, 'present_attendees', 40)
  })

  test('crear regla POR RESERVA (per_plan_price + active_enrollments, 60%)', async ({ page }) => {
    await createPctRule(page, 'active_enrollments', 60)
  })
})
