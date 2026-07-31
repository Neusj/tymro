// Helpers de formato compartidos por la UI de pagos. Antes estaban copiados
// inline en varias páginas (clp en PayoutStatus/TeacherPayments*, firstApiError
// en PlanListPage/StudentPlansPage); aquí quedan en un solo lugar reutilizable.

// Pesos chilenos: "$12.345" (es-CL, separador de miles con punto, sin decimales).
export const clp = (value) =>
  `$${Math.round(Number(value) || 0).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`

// Un DateField de DRF llega como 'YYYY-MM-DD', y `new Date('2026-07-30')` lo interpreta
// como medianoche UTC — que en Chile (UTC-3/-4) es el día ANTERIOR a las 21:00. Cada tabla
// que mostraba start_date/end_date restaba un día en silencio. Con 'T00:00:00' se parsea
// como medianoche LOCAL y la fecha rendereada es la que mandó el backend.
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

export const formatDate = (value) => {
  if (!value) return '-'
  const date = new Date(DATE_ONLY.test(value) ? `${value}T00:00:00` : value)
  if (Number.isNaN(date.getTime())) return value
  // Locale explícito: sin él, `toLocaleDateString()` sigue al del navegador y una máquina
  // en inglés mostraba '7/30/2026' dentro de una UI en español.
  return date.toLocaleDateString('es-CL')
}

// "Hoy" para PRELLENAR un campo de fecha que se va a ENVIAR al backend. `toISOString()`
// normaliza a UTC, así que después de las 20:00 hora de Chile proponía el día siguiente y
// corría la ventana completa de la membresía. Esto lee el calendario local.
export const todayLocalISO = () => {
  const now = new Date()
  const pad = (part) => String(part).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

// Desempaqueta el cuerpo de error de DRF a un string legible.
// Acepta: string plano, {detail: '...'}, o {campo: ['error', ...]}.
export const firstApiError = (detail, fallback) => {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (detail.detail) return detail.detail
  const firstValue = Object.values(detail)[0]
  if (Array.isArray(firstValue) && firstValue[0]) return firstValue[0]
  if (typeof firstValue === 'string') return firstValue
  return fallback
}
