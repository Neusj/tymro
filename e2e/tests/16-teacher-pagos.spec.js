import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { gymAdminCtx, getRefs, createFutureClass, ensureUnlimitedStudents, enrollActive, setAttendance, completeEarly, setSingleRule } from '../fixtures/teacherProvision.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
let gymClass
let periodMonth // 'YYYY-MM' del mes de la clase

function monthRange(month) {
  const [y, m] = month.split('-').map(Number)
  const lastDay = new Date(y, m, 0).getDate()
  return { from: `${month}-01`, to: `${month}-${String(lastDay).padStart(2, '0')}` }
}

test.beforeAll(async () => {
  fx = loadFixtures()
  const me = teacherUserFromStorage()
  const ctx = await gymAdminCtx(fx)
  const refs = await getRefs(ctx, me)
  await setSingleRule(ctx, refs.teacherId, { payment_type: 'fixed_per_class', amount: 5000 })
  const students = await ensureUnlimitedStudents(ctx, refs, 2)
  const tag = String(Date.now()).slice(-5)
  gymClass = await createFutureClass(ctx, refs, { name: `E2E Pagos ${tag}`, startOffsetMin: 600 })
  for (const s of students) await enrollActive(ctx, gymClass.id, s.id)
  await setAttendance(ctx, gymClass.id) // todos presentes
  await completeEarly(ctx, gymClass.id) // dispara el cálculo → TeacherPaymentRecord ($5.000)
  periodMonth = String(gymClass.start_datetime).slice(0, 7)
  await ctx.dispose()
})

test.describe('16. Mis pagos del profesor', () => {
  test('muestra total/desglose del período y exporta CSV', async ({ page }) => {
    await page.goto('/teacher/payments')
    await expect(page.getByRole('heading', { name: 'Mis pagos' })).toBeVisible()

    await page.getByLabel('Período').fill(periodMonth)

    await expect(page.getByText(/Total del período/)).toBeVisible()
    await expect(page.getByText('Sueldo base', { exact: true })).toBeVisible()
    await expect(page.getByText('Por clase', { exact: true })).toBeVisible() // exact: evita "Fijo por clase"
    await expect(page.getByText(gymClass.name)).toBeVisible() // la clase del período en el detalle

    // Export CSV: descarga real disparada por <a download>.
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'CSV' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/mis_pagos_.*\.csv/)
  })

  test('verifica el monto y el export por API (scopeado al profesor)', async ({ page }) => {
    const { from, to } = monthRange(periodMonth)
    const ctx = await apiContext(teacherTokenFromStorage())

    const summary = await ctx.get(`teacher-payments/summary/?date_from=${from}&date_to=${to}`)
    expect(summary.ok()).toBeTruthy()
    const data = await summary.json()
    const row = (data.rows || [])[0]
    expect(row, 'el profesor debe tener una fila de resumen').toBeTruthy()
    expect(row.per_class_total, 'el pago por clase del período debe incluir los $5.000').toBeGreaterThanOrEqual(5000)

    const csv = await ctx.get(`teacher-payments/summary/export/?date_from=${from}&date_to=${to}&fmt=csv`)
    expect(csv.ok()).toBeTruthy()
    expect((await csv.text()).length).toBeGreaterThan(0)
    await ctx.dispose()
  })
})
