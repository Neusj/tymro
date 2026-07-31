import { describe, it, expect } from 'vitest'
import { clp, firstApiError, formatDate, todayLocalISO } from './format'

// Las fechas del backend son DateField ('2026-07-30'): sin hora y ya en America/Santiago.
// Toda esta sección depende de correr en una zona al oeste de UTC — la fija
// vitest.config.js (test.env.TZ). Sin eso los tests pasarían incluso con el bug.
describe('zona horaria de la suite', () => {
  it('corre en America/Santiago (si no, los tests de fecha no prueban nada)', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/Santiago')
  })
})

describe('formatDate', () => {
  it('no corre la fecha un día hacia atrás (bug UTC)', () => {
    // `new Date('2026-07-30')` es medianoche UTC = 29-07 21:00 en Santiago.
    expect(formatDate('2026-07-30')).toBe('30-07-2026')
  })

  it('respeta el día en el borde de mes y de año', () => {
    expect(formatDate('2026-01-01')).toBe('01-01-2026')
    expect(formatDate('2026-03-01')).toBe('01-03-2026')
  })

  it('usa es-CL y no el locale del navegador', () => {
    // en-US daría '7/30/2026'; el formato chileno es dd-mm-aaaa.
    expect(formatDate('2026-07-30')).toMatch(/^\d{2}-\d{2}-\d{4}$/)
  })

  it('devuelve un guion cuando no hay fecha', () => {
    expect(formatDate('')).toBe('-')
    expect(formatDate(null)).toBe('-')
    expect(formatDate(undefined)).toBe('-')
  })

  it('devuelve el valor original si no es una fecha parseable', () => {
    expect(formatDate('no-es-fecha')).toBe('no-es-fecha')
  })

  it('acepta también un datetime ISO sin romperse', () => {
    // enrollment_fee_paid_at y compañía llegan con hora; no se les añade T00:00:00.
    expect(formatDate('2026-07-30T15:00:00Z')).toBe('30-07-2026')
  })
})

describe('todayLocalISO', () => {
  it('devuelve la fecha LOCAL, no la UTC, después de las 20:00 en Chile', () => {
    // 2026-07-31 01:30 UTC = 2026-07-30 21:30 en Santiago (UTC-4 en invierno).
    // `new Date().toISOString().slice(0,10)` daría '2026-07-31' y correría la
    // ventana entera de la membresía un día hacia adelante.
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-31T01:30:00Z'))
    try {
      expect(todayLocalISO()).toBe('2026-07-30')
    } finally {
      vi.useRealTimers()
    }
  })

  it('mantiene el día cuando UTC y la hora local coinciden en fecha', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-30T15:00:00Z'))
    try {
      expect(todayLocalISO()).toBe('2026-07-30')
    } finally {
      vi.useRealTimers()
    }
  })

  it('rellena mes y día a dos dígitos', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-03-05T15:00:00Z'))
    try {
      expect(todayLocalISO()).toBe('2026-03-05')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('clp', () => {
  it('formatea CLP con separador de miles es-CL y sin decimales', () => {
    expect(clp(12345)).toBe('$12.345')
    expect(clp(1000000)).toBe('$1.000.000')
  })

  it('redondea y trata valores no numéricos como 0', () => {
    expect(clp(12345.67)).toBe('$12.346')
    expect(clp(null)).toBe('$0')
    expect(clp(undefined)).toBe('$0')
    expect(clp('no-num')).toBe('$0')
  })

  it('acepta strings decimales (como el enrollment_fee del backend)', () => {
    expect(clp('15000.00')).toBe('$15.000')
  })
})

describe('firstApiError', () => {
  it('devuelve el fallback cuando no hay detalle', () => {
    expect(firstApiError(null, 'fallback')).toBe('fallback')
    expect(firstApiError(undefined, 'fallback')).toBe('fallback')
  })

  it('devuelve un string plano tal cual', () => {
    expect(firstApiError('boom', 'fallback')).toBe('boom')
  })

  it('prioriza la clave detail de DRF', () => {
    expect(firstApiError({ detail: 'no conectado' }, 'fallback')).toBe('no conectado')
  })

  it('extrae el primer error de campo (array)', () => {
    expect(firstApiError({ plan_id: ['requerido'] }, 'fallback')).toBe('requerido')
  })

  it('extrae el primer error de campo (string)', () => {
    expect(firstApiError({ plan_id: 'requerido' }, 'fallback')).toBe('requerido')
  })
})
