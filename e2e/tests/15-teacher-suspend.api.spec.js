import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { gymAdminCtx, getRefs, createFutureClass } from '../fixtures/teacherProvision.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
let gymClass

test.beforeAll(async () => {
  fx = loadFixtures()
  const me = teacherUserFromStorage()
  const ctx = await gymAdminCtx(fx)
  const refs = await getRefs(ctx, me)
  const tag = String(Date.now()).slice(-5)
  gymClass = await createFutureClass(ctx, refs, { name: `E2E SuspendAPI ${tag}`, startOffsetMin: 520 })
  await ctx.dispose()
})

test.describe('15. Suspender y reactivar (API, como profesor)', () => {
  test('el profesor suspende y reactiva su propia clase', async ({ page }) => {
    const ctx = await apiContext(teacherTokenFromStorage())

    const suspend = await ctx.post(`classes/${gymClass.id}/suspend/`, { data: { suspend_reason: 'Mantención (E2E)' } })
    expect(suspend.status(), 'suspend debe responder 200').toBe(200)
    expect((await suspend.json()).status).toBe('suspended')
    // El email a los inscritos se dispara server-side (fail_silently); no es verificable en E2E.

    const reactivate = await ctx.post(`classes/${gymClass.id}/reactivate/`)
    expect(reactivate.status(), 'reactivate debe responder 200').toBe(200)
    expect((await reactivate.json()).status).toBe('scheduled') // clase futura → vuelve a programada

    await ctx.dispose()
  })

  test('reactivar una clase NO suspendida → 400', async ({ page }) => {
    const ctx = await apiContext(teacherTokenFromStorage())
    const res = await ctx.post(`classes/${gymClass.id}/reactivate/`)
    expect(res.status()).toBe(400)
    await ctx.dispose()
  })
})
