import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { openRowAction, searchClass } from '../fixtures/helpers.js'
import { gymAdminCtx, getRefs, createFutureClass, ensureUnlimitedStudents } from '../fixtures/teacherProvision.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
let gymClass
let students

async function enrolledStudentIds() {
  const ctx = await apiContext(teacherTokenFromStorage())
  const res = await ctx.get(`classes/${gymClass.id}/enrolled-students/`)
  const data = await res.json()
  const ids = (Array.isArray(data) ? data : data.results || []).map((s) => s.student_id)
  await ctx.dispose()
  return ids
}

test.beforeAll(async () => {
  fx = loadFixtures()
  const me = teacherUserFromStorage()
  const ctx = await gymAdminCtx(fx)
  const refs = await getRefs(ctx, me)
  students = await ensureUnlimitedStudents(ctx, refs, 4) // s1..s4 con plan ilimitado
  const tag = String(Date.now()).slice(-5)
  gymClass = await createFutureClass(ctx, refs, { name: `E2E Inscripciones ${tag}`, startOffsetMin: 280 })
  await ctx.dispose()
})

test.describe('13. Inscribir y quitar alumnos', () => {
  test('inscribe un alumno desde la UI y queda activo', async ({ page }) => {
    await page.goto('/teacher/classes/upcoming')
    await searchClass(page, gymClass.name)
    await openRowAction(page, gymClass.name, 'Inscribir alumnos')

    const dialog = page.getByRole('dialog', { name: /Inscribir alumnos/ })
    await expect(dialog).toBeVisible()
    await dialog.getByPlaceholder('Nombre, username o email').fill(students[3].username)
    await dialog.locator('label').filter({ hasText: students[3].username }).locator('input[type="checkbox"]').check()

    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/enrollments/') && r.request().method() === 'POST'),
      dialog.getByRole('button', { name: 'Inscribir seleccionados' }).click(),
    ])
    expect(resp.ok()).toBeTruthy()

    expect(await enrolledStudentIds()).toContain(students[3].id)
  })

  test('quita un alumno desde la UI y deja de estar inscrito', async ({ page }) => {
    await page.goto('/teacher/classes/upcoming')
    await searchClass(page, gymClass.name)
    await openRowAction(page, gymClass.name, 'Ver inscritos')

    const dialog = page.getByRole('dialog', { name: /Ver inscritos/ })
    await expect(dialog).toBeVisible()
    await dialog.locator('label').filter({ hasText: students[3].username }).locator('input[type="checkbox"]').check()

    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/cancel/') && r.request().method() === 'POST'),
      dialog.getByRole('button', { name: 'Quitar seleccionados' }).click(),
    ])
    expect(resp.ok()).toBeTruthy()

    expect(await enrolledStudentIds()).not.toContain(students[3].id)
  })

  test('rechazo: alumno ya inscrito → 400 con mensaje claro (API)', async ({ page }) => {
    const ctx = await apiContext(teacherTokenFromStorage())
    const body = { gym_class: gymClass.id, student: students[1].id, status: 'active' }

    const first = await ctx.post('enrollments/', { data: body })
    expect([200, 201], 'la primera inscripción debe crearse').toContain(first.status())

    const dup = await ctx.post('enrollments/', { data: body })
    expect(dup.status(), 'la inscripción duplicada debe rechazarse').toBe(400)
    const dupBody = await dup.json().catch(() => ({}))
    const msg = dupBody.detail || Object.values(dupBody).flat()[0] || ''
    expect(String(msg)).toContain('ya tiene una reserva')

    // Limpieza: cancelar la inscripción creada para no dejar estado.
    const created = await first.json().catch(() => ({}))
    if (created.id) {
      await ctx.post(`enrollments/${created.id}/cancel/`)
    }
    await ctx.dispose()
  })
})
