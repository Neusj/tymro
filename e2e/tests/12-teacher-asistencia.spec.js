import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { openRowAction, searchClass } from '../fixtures/helpers.js'
import { gymAdminCtx, getRefs, createFutureClass, ensureUnlimitedStudents, enrollActive } from '../fixtures/teacherProvision.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
let gymClass
let students // [{id, username}] con nombres AlumnoE2E1/2/3

test.beforeAll(async () => {
  fx = loadFixtures()
  const me = teacherUserFromStorage()
  const ctx = await gymAdminCtx(fx)
  const refs = await getRefs(ctx, me)
  students = await ensureUnlimitedStudents(ctx, refs, 3)
  const tag = String(Date.now()).slice(-5)
  gymClass = await createFutureClass(ctx, refs, { name: `E2E Asistencia ${tag}`, startOffsetMin: 200 })
  for (const s of students) {
    await enrollActive(ctx, gymClass.id, s.id)
  }
  await ctx.dispose()
})

test.describe('12. Tomar asistencia', () => {
  test('marca present/absent/late, guarda y persiste en el backend', async ({ page }) => {
    await page.goto('/teacher/classes/upcoming')
    await searchClass(page, gymClass.name)
    await openRowAction(page, gymClass.name, 'Tomar asistencia')

    const dialog = page.getByRole('dialog', { name: /Asistencia/ })
    await expect(dialog).toBeVisible()

    // Marcar cada alumno con un estado distinto, scopeado al <label> del alumno (por su
    // nombre del roster). OJO: el <label> envuelve los botones, así que el botón "Presente"
    // hereda como accessible-name el texto del label → hay que localizar por TEXTO del botón.
    await dialog.locator('label').filter({ hasText: students[0].firstName }).locator('button', { hasText: 'Presente' }).click()
    await dialog.locator('label').filter({ hasText: students[1].firstName }).locator('button', { hasText: 'Ausente' }).click()
    await dialog.locator('label').filter({ hasText: students[2].firstName }).locator('button', { hasText: 'Tarde' }).click()

    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes(`/classes/${gymClass.id}/attendance/`) && r.request().method() === 'POST'),
      dialog.getByRole('button', { name: 'Guardar asistencia' }).click(),
    ])
    expect(resp.ok(), 'el POST de asistencia debe responder 2xx').toBeTruthy()

    // Verificación API: la asistencia quedó persistida con los 3 estados.
    const ctx = await apiContext(teacherTokenFromStorage())
    const detail = await ctx.get(`classes/${gymClass.id}/`)
    expect(detail.ok()).toBeTruthy()
    const data = await detail.json()
    const statuses = (data.attendances || []).map((a) => a.status)
    expect(statuses).toContain('present')
    expect(statuses).toContain('absent')
    expect(statuses).toContain('late')
    await ctx.dispose()
  })
})
