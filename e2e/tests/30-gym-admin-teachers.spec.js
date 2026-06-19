import { test, expect } from '@playwright/test'
import { searchClass } from '../fixtures/helpers.js'

// Gestión de profesores: crear un usuario con rol teacher desde /gym-admin/users.
test.describe('30. Profesores (CRUD usuarios) gym_admin', () => {
  test('crear un profesor', async ({ page }) => {
    const uname = `e2eprof${Date.now()}`
    await page.goto('/gym-admin/users')
    await expect(page.getByRole('heading', { name: 'Gym Admin · Usuarios' })).toBeVisible()

    await page.getByRole('button', { name: 'Crear usuario' }).click()
    const d = page.getByRole('dialog', { name: 'Crear usuario' })
    await d.getByLabel('Nombre').fill('Profe')
    await d.getByLabel('Username').fill(uname)
    await d.getByLabel('Rol').selectOption('teacher')
    await d.getByLabel(/Contraseña/).fill('Passw0rd2026')
    await d.getByRole('button', { name: /Guardar|Crear usuario/ }).click()
    await expect(d).toBeHidden() // el modal cierra al guardar OK

    // La tabla pagina: buscamos al nuevo profesor por su username.
    await searchClass(page, uname)
    await expect(page.getByRole('main').getByText(uname, { exact: true }).first()).toBeVisible()
  })
})
