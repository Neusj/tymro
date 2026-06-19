import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, apiLogin, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { openRowAction, searchClass } from '../fixtures/helpers.js'
import { gymAdminCtx, getRefs, createFutureClass, ensureUnlimitedStudents, ensureBalanceStudent, enrollActive } from '../fixtures/teacherProvision.js'

// Viewport alto: el menú de acciones por fila (portal) tiene 6 ítems; con la altura
// por defecto (720) los últimos ('Cancelar clase') quedan fuera del área clickeable.
test.use({ storageState: 'storageState.teacher.json', viewport: { width: 1280, height: 1400 } })

let fx
let suspendClass
let cancelClass
let balanceStudent

async function classStatus(id) {
  const ctx = await apiContext(teacherTokenFromStorage())
  const res = await ctx.get(`classes/${id}/`)
  const data = await res.json()
  await ctx.dispose()
  return data.status
}

test.beforeAll(async () => {
  fx = loadFixtures()
  const me = teacherUserFromStorage()
  const ctx = await gymAdminCtx(fx)
  const refs = await getRefs(ctx, me)
  const [unlimited] = await ensureUnlimitedStudents(ctx, refs, 1)
  balanceStudent = await ensureBalanceStudent(ctx, refs, { total: 10 })
  const tag = String(Date.now()).slice(-5)
  suspendClass = await createFutureClass(ctx, refs, { name: `E2E Suspender ${tag}`, startOffsetMin: 360 })
  cancelClass = await createFutureClass(ctx, refs, { name: `E2E Cancelar ${tag}`, startOffsetMin: 440 })
  await enrollActive(ctx, suspendClass.id, unlimited.id) // un inscrito (receptor del email de suspensión)
  await enrollActive(ctx, cancelClass.id, balanceStudent.id) // consume 1 clase de su saldo
  await ctx.dispose()
})

test.describe('14. Cierre de clases: suspender, finalizar, cancelar', () => {
  // H1 (corregido): el botón "Suspender clase" ahora llama al endpoint suspend real
  // (estado SUSPENDED + email), NO a complete-early. Es una pausa reactivable.
  test('"Suspender clase" deja la clase en estado suspended', async ({ page }) => {
    // El flujo usa window.prompt: lo sobreescribimos (determinista) y, por las dudas,
    // también aceptamos el evento 'dialog'. Verificamos el efecto real por API (poll).
    await page.addInitScript(() => { window.prompt = () => 'Profesor enfermo E2E' })
    page.on('dialog', (dialog) => dialog.accept('Profesor enfermo E2E'))

    await page.goto('/teacher/classes/upcoming')
    await searchClass(page, suspendClass.name)
    await openRowAction(page, suspendClass.name, 'Suspender clase')

    await expect.poll(() => classStatus(suspendClass.id), { timeout: 20_000 }).toBe('suspended')
  })

  // H2 (corregido): cancelar la clase ahora DEVUELVE la clase consumida al plan del
  // alumno y deja su inscripción cancelada.
  test('"Cancelar clase" cancela y devuelve el saldo al alumno', async ({ page }) => {
    await page.addInitScript(() => { window.prompt = () => 'Sin quorum E2E' })
    page.on('dialog', (dialog) => dialog.accept('Sin quorum E2E'))

    await page.goto('/teacher/classes/upcoming')
    await searchClass(page, cancelClass.name)
    await openRowAction(page, cancelClass.name, 'Cancelar clase')

    await expect.poll(() => classStatus(cancelClass.id), { timeout: 20_000 }).toBe('cancelled')

    // El alumno recuperó la clase (classes_used vuelve a 0, remaining al total).
    const { token, ctx: loginCtx } = await apiLogin(balanceStudent.username, balanceStudent.password)
    await loginCtx.dispose()
    const ctx = await apiContext(token)
    const planRes = await ctx.get('plans/my-plan/')
    expect(planRes.ok()).toBeTruthy()
    const plan = await planRes.json()
    expect(plan.classes_used, 'la clase consumida debe devolverse al cancelar').toBe(0)
    expect(plan.remaining_classes).toBe(plan.total_classes)
    await ctx.dispose()
  })
})
