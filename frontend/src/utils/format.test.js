import { describe, it, expect } from 'vitest'
import { clp, firstApiError } from './format'

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
