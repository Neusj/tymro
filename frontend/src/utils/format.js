// Helpers de formato compartidos por la UI de pagos. Antes estaban copiados
// inline en varias páginas (clp en PayoutStatus/TeacherPayments*, firstApiError
// en PlanListPage/StudentPlansPage); aquí quedan en un solo lugar reutilizable.

// Pesos chilenos: "$12.345" (es-CL, separador de miles con punto, sin decimales).
export const clp = (value) =>
  `$${Math.round(Number(value) || 0).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`

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
