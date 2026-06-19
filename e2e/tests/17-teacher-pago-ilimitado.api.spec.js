import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { gymAdminCtx, getRefs, createFutureClass, ensureUnlimitedStudents, enrollActive, setAttendance, completeEarly, setSingleRule } from '../fixtures/teacherProvision.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
let gymClass
let periodMonth

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
  // Regla % del precio por clase sobre PRESENTES → los planes ilimitados se excluyen.
  await setSingleRule(ctx, refs.teacherId, {
    payment_type: 'per_plan_price',
    amount: 50,
    extra: { per_plan_price_base: 'present_attendees' },
  })
  const [unlimited] = await ensureUnlimitedStudents(ctx, refs, 1)
  const tag = String(Date.now()).slice(-5)
  gymClass = await createFutureClass(ctx, refs, { name: `E2E Ilimitado ${tag}`, startOffsetMin: 680 })
  await enrollActive(ctx, gymClass.id, unlimited.id)
  await setAttendance(ctx, gymClass.id) // alumno ilimitado presente
  await completeEarly(ctx, gymClass.id) // dispara el cálculo de pago
  periodMonth = String(gymClass.start_datetime).slice(0, 7)
  await ctx.dispose()
})

test.describe('17. Pago con plan ilimitado (limitación conocida)', () => {
  // LIMITACIÓN CONOCIDA (no es bug): los planes ilimitados se EXCLUYEN de la base de
  // revenue/per_plan_price (teacher_payments.py:66). Un alumno ilimitado aporta $0.
  test('un alumno con plan ilimitado aporta $0 al pago del profesor', async ({ page }) => {
    const { from, to } = monthRange(periodMonth)
    const ctx = await apiContext(teacherTokenFromStorage())
    const res = await ctx.get(`teacher-payments/summary/?date_from=${from}&date_to=${to}`)
    expect(res.ok()).toBeTruthy()
    const data = await res.json()
    const row = (data.rows || [])[0]
    expect(row).toBeTruthy()
    const cls = (row.classes || []).find((c) => c.id === gymClass.id)
    expect(cls, 'la clase del período debe aparecer en el detalle').toBeTruthy()
    expect(Number(cls.amount), 'plan ilimitado → aporta $0').toBe(0)
    await ctx.dispose()
  })
})
