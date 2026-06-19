import { test, expect } from '@playwright/test'
import { gymApi } from '../fixtures/gymAdmin.js'

// Validaciones de rechazo reales del backend (API), como gym_admin.
test.describe('37. Validaciones de rechazo (API) gym_admin', () => {
  let api
  test.beforeAll(async () => { api = await gymApi() })
  test.afterAll(async () => { await api?.dispose() })

  test('sucursal con nombre duplicado (case-insensitive) → 400', async () => {
    const name = `E2E ValBranch ${Date.now()}`
    const first = await api.post('branches/', { data: { name } })
    expect(first.status()).toBe(201)
    const dup = await api.post('branches/', { data: { name: name.toUpperCase() } })
    expect(dup.status()).toBe(400)
  })

  test('disciplina con nombre vacío → 400', async () => {
    const res = await api.post('disciplines/', { data: { name: '  ' } })
    expect(res.status()).toBe(400)
  })

  test('regla per_plan_price con porcentaje > 100 → 400', async () => {
    const res = await api.post('teacher-payment-rules/', {
      data: { payment_type: 'per_plan_price', per_plan_price_base: 'present_attendees', amount: 150 },
    })
    expect(res.status()).toBe(400)
  })

  test('regla per_plan_price sin base → 400', async () => {
    const res = await api.post('teacher-payment-rules/', {
      data: { payment_type: 'per_plan_price', amount: 40 },
    })
    expect(res.status()).toBe(400)
  })
})
