import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, apiLogin, studentTokenFromStorage } from '../fixtures/data.js'
import { openRowAction } from '../fixtures/helpers.js'

let fx
test.beforeAll(() => { fx = loadFixtures() })

// Reserva por API y devuelve { status, body }.
async function reserve(ctx, gymClassId) {
  const res = await ctx.post('enrollments/', { data: { gym_class: gymClassId, status: 'active' } })
  return { status: res.status(), body: await res.json().catch(() => ({})) }
}

// Mensaje de error sin importar la forma ({detail} o {campo:[...]}).
function firstMessage(body) {
  if (!body) return ''
  if (typeof body.detail === 'string') return body.detail
  const first = Object.values(body)[0]
  return Array.isArray(first) ? first[0] : String(first ?? '')
}

test.describe('9. Rechazos esperados (validaciones críticas)', () => {
  test('cupo lleno → error claro (UI)', async ({ page }) => {
    await page.goto('/student/classes/available')
    await openRowAction(page, fx.full_class.name, 'Reservar solo esta clase')
    await expect(page.getByText('La clase ya alcanzó su capacidad máxima.')).toBeVisible()
  })

  test('cupo lleno → rechazo del backend (API)', async () => {
    const ctx = await apiContext(studentTokenFromStorage())
    const { status, body } = await reserve(ctx, fx.full_class.id)
    expect(status).toBe(400)
    expect(firstMessage(body)).toBe('La clase ya alcanzó su capacidad máxima.')
    await ctx.dispose()
  })

  test('solape horario → rechazo del backend (API)', async () => {
    const ctx = await apiContext(studentTokenFromStorage())
    // Reserva la primera (debe quedar activa)...
    const first = await reserve(ctx, fx.overlap_1.id)
    expect([200, 201]).toContain(first.status)
    // ...y la segunda al mismo horario debe rechazarse.
    const second = await reserve(ctx, fx.overlap_2.id)
    expect(second.status).toBe(400)
    expect(firstMessage(second.body)).toContain('otra clase reservada o confirmada en ese horario')

    // Limpieza: cancelar la primera para no dejar saldo consumido.
    if (first.body?.id) {
      await ctx.post(`enrollments/${first.body.id}/cancel/`)
    }
    await ctx.dispose()
  })

  test('sin plan activo → error claro (API)', async () => {
    const { token, ctx: loginCtx } = await apiLogin(fx.rejection_students.no_plan, 'student123')
    await loginCtx.dispose()
    const ctx = await apiContext(token)
    const { status, body } = await reserve(ctx, fx.reservable_a.id)
    expect(status).toBe(400)
    expect(firstMessage(body)).toBe('No tienes clases disponibles o plan activo')
    await ctx.dispose()
  })

  test('saldo insuficiente → error claro (API)', async () => {
    const { token, ctx: loginCtx } = await apiLogin(fx.rejection_students.no_balance, 'student123')
    await loginCtx.dispose()
    const ctx = await apiContext(token)
    const { status, body } = await reserve(ctx, fx.reservable_a.id)
    expect(status).toBe(400)
    expect(firstMessage(body)).toBe('No tienes clases disponibles o plan activo')
    await ctx.dispose()
  })

  test('matrícula impaga → error claro (API)', async () => {
    const { token, ctx: loginCtx } = await apiLogin(fx.rejection_students.unpaid, 'student123')
    await loginCtx.dispose()
    const ctx = await apiContext(token)
    const { status, body } = await reserve(ctx, fx.reservable_a.id)
    expect(status).toBe(400)
    expect(firstMessage(body)).toBe('Debes pagar la matrícula de tu plan antes de reservar.')
    await ctx.dispose()
  })
})
