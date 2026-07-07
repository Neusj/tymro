// RUT chileno: espejo de backend/accounts/rut.py (mantener en sync).
// Canónico: sin puntos, con guion, K mayúscula (ej. 26711486-2). El backend
// es la frontera real; esto es solo UX (auto-formateo + validación previa).

const FACTORS = [2, 3, 4, 5, 6, 7]

// Dígito verificador (Módulo 11) del cuerpo numérico: '0'-'9' o 'K'.
export function computeDv(body) {
  if (!/^\d+$/.test(body)) return null
  let total = 0
  const reversed = body.split('').reverse()
  for (let i = 0; i < reversed.length; i += 1) {
    total += Number(reversed[i]) * FACTORS[i % 6]
  }
  const remainder = 11 - (total % 11)
  if (remainder === 11) return '0'
  if (remainder === 10) return 'K'
  return String(remainder)
}

// Normaliza a canónico y valida el DV; devuelve null si es vacío/malformado/DV incorrecto.
export function toCanonical(value) {
  if (value == null) return null
  const normalized = String(value).trim().toUpperCase().replace(/\./g, '').replace(/\s/g, '')
  if (!normalized) return null

  let body
  let dv
  if (normalized.includes('-')) {
    const parts = normalized.split('-')
    if (parts.length !== 2) return null
    ;[body, dv] = parts
  } else {
    body = normalized.slice(0, -1)
    dv = normalized.slice(-1)
  }

  if (!/^\d+$/.test(body)) return null
  if (!/^[0-9K]$/.test(dv)) return null
  if (computeDv(body) !== dv) return null
  return `${body}-${dv}`
}

// True si es un RUT válido (formato + Módulo 11). Nunca lanza.
export function isValidRut(value) {
  return toCanonical(value) !== null
}

// Auto-formateo en curso para un input controlado: agrupa el cuerpo con puntos
// y agrega el guion antes del DV (último carácter). No valida el DV.
export function formatRut(value) {
  const cleaned = String(value ?? '').toUpperCase().replace(/[^0-9K]/g, '')
  if (cleaned.length <= 1) return cleaned
  const body = cleaned.slice(0, -1).replace(/K/g, '')  // el cuerpo es solo dígitos
  const dv = cleaned.slice(-1)
  const grouped = body.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${grouped}-${dv}`
}
