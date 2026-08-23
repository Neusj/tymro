import { test, expect } from '@playwright/test'
import { loadFixtures, apiContext, teacherTokenFromStorage, teacherUserFromStorage } from '../fixtures/data.js'
import { selectFilter, searchClass } from '../fixtures/helpers.js'
import { gymAdminCtx, getRefs, createFutureClass } from '../fixtures/teacherProvision.js'

test.use({ storageState: 'storageState.teacher.json' })

let fx
let me
let listClass // clase programada desechable para asserts deterministas de filtro

test.beforeAll(async () => {
  fx = loadFixtures()
  me = teacherUserFromStorage()
  const ctx = await gymAdminCtx(fx)
  const refs = await getRefs(ctx, me)
  const tag = String(Date.now()).slice(-5)
  listClass = await createFutureClass(ctx, refs, { name: `E2E Listado ${tag}`, startOffsetMin: 120 })
  await ctx.dispose()
})

test.describe('11. Clases del profesor (ver, filtros, historial)', () => {
  test('próximas clases muestra mis clases y los KPIs', async ({ page }) => {
    await page.goto('/teacher/classes/upcoming')
    await expect(page.getByRole('heading', { name: 'Teacher · Mis clases' })).toBeVisible()

    // KPIs visibles (KpiStrip desktop).
    await expect(page.getByText('Total clases')).toBeVisible()
    await expect(page.getByText('Total inscritos')).toBeVisible()

    // La clase recién provisionada aparece en la tabla (la busco por si está en otra página).
    await searchClass(page, listClass.name)
    await expect(page.getByRole('row', { name: listClass.name })).toBeVisible()

    // Verificación API: el listado del profesor está scopeado a SUS clases.
    const ctx = await apiContext(teacherTokenFromStorage())
    const res = await ctx.get('classes/?status_in=scheduled,in_progress,suspended')
    expect(res.ok()).toBeTruthy()
    const data = await res.json()
    const rows = Array.isArray(data) ? data : data.results || []
    expect(rows.length, 'el profesor debe ver al menos 1 clase propia').toBeGreaterThan(0)
    expect(rows.every((c) => !c.teacher || c.teacher === me.id), 'todas las clases son del profesor logueado').toBeTruthy()
    await ctx.dispose()
  })

  test('filtro por estado oculta/muestra la clase programada', async ({ page }) => {
    await page.goto('/teacher/classes/upcoming')
    await searchClass(page, listClass.name)
    const row = page.getByRole('row', { name: listClass.name })
    await expect(row).toBeVisible()

    // Filtrar a "En curso" → la clase programada desaparece.
    await selectFilter(page, 'Estado', 'En curso')
    await expect(page.getByRole('row', { name: listClass.name })).toHaveCount(0)

    // Volver a "Programada" → reaparece.
    await selectFilter(page, 'Estado', 'Programada')
    await expect(page.getByRole('row', { name: listClass.name })).toBeVisible()
  })

  test('historial muestra clases realizadas y KPI de asistentes', async ({ page }) => {
    await page.goto('/teacher/classes/history')
    await expect(page.getByRole('heading', { name: 'Teacher · Clases realizadas' })).toBeVisible()
    await expect(page.getByText('Total asistentes')).toBeVisible()
  })
})
