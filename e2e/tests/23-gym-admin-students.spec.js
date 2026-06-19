import { test, expect } from '@playwright/test'

// Estudiantes: crear un alumno y asignarle un plan (flujo de membresías).
test.describe('23. Estudiantes gym_admin', () => {
  test('crear un alumno', async ({ page }) => {
    const uname = `e2estu${Date.now()}`
    await page.goto('/gym-admin/users')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Usuarios' })).toBeVisible()

    await page.getByRole('button', { name: 'Crear usuario' }).click()
    const d = page.getByRole('dialog', { name: 'Crear usuario' })
    await d.getByLabel('Nombre').fill('Alumno')
    await d.getByLabel('Username').fill(uname)
    await d.getByLabel('Rol').selectOption('student')
    await d.getByLabel(/Contraseña/).fill('Passw0rd2026')
    await d.getByRole('button', { name: /Guardar|Crear usuario/ }).click()
    await expect(d).toBeHidden()
  })

  test('asignar un plan a un alumno', async ({ page }) => {
    await page.goto('/gym-admin/plans/assign')
    await expect(page.getByRole('heading', { name: 'Asignar plan' })).toBeVisible()
    const main = page.getByRole('main')

    const selects = main.getByRole('combobox') // [0]=Alumno, [1]=Plan
    await selects.nth(0).selectOption({ index: 1 }) // index 0 = "Seleccionar alumno"
    await selects.nth(1).selectOption({ index: 1 }) // primer plan real
    await main.getByLabel('Fecha inicio').fill('2026-06-20')
    await main.getByRole('button', { name: 'Asignar plan' }).click()

    await expect(main.getByText('Plan asignado correctamente.')).toBeVisible()
  })
})
