import { test, expect } from '@playwright/test'
import { fixtures, gymApi, teacherIdByUsername } from '../fixtures/gymAdmin.js'

// Validación API-driven del CÁLCULO REAL del backend (montos exactos), end-to-end:
// el seed dejó clases COMPLETED con asistencia/planes; el backend calculó al cerrar;
// aquí leemos el resumen como gym_admin y aseguramos los montos.
test.describe('32. Cálculo de pago a profesor — montos exactos (API)', () => {
  let api
  let pc

  test.beforeAll(async () => {
    api = await gymApi()
    pc = fixtures().payment_calc
  })

  test.afterAll(async () => {
    await api?.dispose()
  })

  async function totalFor(username) {
    const tid = await teacherIdByUsername(api, username)
    const res = await api.get('teacher-payments/summary/')
    expect(res.ok(), `summary status ${res.status()}`).toBeTruthy()
    const data = await res.json()
    const row = data.rows.find((r) => r.teacher_id === tid)
    expect(row, `fila de pago para ${username}`).toBeTruthy()
    return row.total
  }

  test('FIJO: $5.000 por clase, sin importar el número de alumnos', async () => {
    expect(await totalFor(pc.fijo.teacher)).toBe(pc.fijo.expected) // 5000
  })

  test('POR ASISTENCIA 40%: (10k + 5k) × 0.4 = $6.000 (ilimitado aporta $0)', async () => {
    expect(await totalFor(pc.asistencia.teacher)).toBe(pc.asistencia.expected) // 6000
  })

  test('POR RESERVA 60%: (10k + 5k) × 0.6 = $9.000 (cobra aunque el alumno falte)', async () => {
    expect(await totalFor(pc.reserva.teacher)).toBe(pc.reserva.expected) // 9000
  })
})
