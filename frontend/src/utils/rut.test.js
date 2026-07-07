import { describe, it, expect } from 'vitest'

import { computeDv, isValidRut, toCanonical, formatRut } from './rut'

// Espejo de backend/accounts/rut.py. DVs calculados a mano (Módulo 11).
describe('computeDv', () => {
  it.each([
    ['12345678', '5'],
    ['26711486', '2'],
    ['11111111', '1'],
    ['20347878', 'K'],
  ])('cuerpo %s -> DV %s', (body, dv) => {
    expect(computeDv(body)).toBe(dv)
  })
})

describe('isValidRut', () => {
  it.each(['12.345.678-5', '12345678-5', '123456785', '20347878-K', '20.347.878-k', '26711486-2'])(
    'válido: %s',
    (value) => expect(isValidRut(value)).toBe(true),
  )

  it.each(['12345678-9', 'not-a-rut', '', null, undefined])(
    'inválido: %s',
    (value) => expect(isValidRut(value)).toBe(false),
  )
})

describe('toCanonical', () => {
  it('normaliza puntos, guion y K minúscula', () => {
    expect(toCanonical('12.345.678-5')).toBe('12345678-5')
    expect(toCanonical('123456785')).toBe('12345678-5')
    expect(toCanonical('20.347.878-k')).toBe('20347878-K')
  })

  it('devuelve null si es inválido', () => {
    expect(toCanonical('12345678-9')).toBeNull()
    expect(toCanonical('')).toBeNull()
    expect(toCanonical(null)).toBeNull()
  })
})

describe('formatRut (auto-formateo en curso)', () => {
  it('agrupa con puntos y guion tratando el último carácter como DV', () => {
    expect(formatRut('123456785')).toBe('12.345.678-5')
    expect(formatRut('12345678k')).toBe('12.345.678-K')
    expect(formatRut('20347878K')).toBe('20.347.878-K')
  })

  it('pasa la K a mayúscula y descarta caracteres inválidos', () => {
    expect(formatRut('1.234.567-k')).toBe('1.234.567-K')
    expect(formatRut('12ab34')).toBe('123-4')
  })

  it('no formatea cadenas de un solo carácter', () => {
    expect(formatRut('1')).toBe('1')
    expect(formatRut('')).toBe('')
  })
})
