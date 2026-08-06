// Paleta de tonos para los gráficos de reportería (P3.4). NO es una paleta nueva: son los
// mismos tokens semánticos que ya usa el resto de la app (tailwind.config.js: brand.orange,
// brand.blue, success, brand.red) — los mismos que StatCard usa como `accent` y que
// GymAdminPaymentsTransactionsPage usa en sus badges de estado. Documentado como diccionario
// fijo (no valores sueltos) para que cada clase Tailwind aparezca completa y literal en el
// código: así el JIT scanner la detecta y la genera.
//
// Asignación por SIGNIFICADO, no arbitraria:
// - 'info' (bruto, capacidad-techo): neutral informativo → brand-blue.
// - 'danger' (devoluciones): negativo → brand-red.
// - 'success' (neto, ocupación real): positivo/resultado → success.
// - 'orange' / 'blue': identidad categórica (ej. efectivo vs transferencia), sin carga de
//   bueno/malo — usan el par primario/secundario de la app.
export const CHART_TONES = {
  info: { stroke: 'stroke-brand-blue', fill: 'fill-brand-blue', dot: 'bg-brand-blue', text: 'text-brand-blue' },
  danger: { stroke: 'stroke-brand-red', fill: 'fill-brand-red', dot: 'bg-brand-red', text: 'text-brand-red' },
  success: { stroke: 'stroke-success', fill: 'fill-success', dot: 'bg-success', text: 'text-success' },
  orange: { stroke: 'stroke-brand-orange', fill: 'fill-brand-orange', dot: 'bg-brand-orange', text: 'text-brand-orange' },
  blue: { stroke: 'stroke-brand-blue', fill: 'fill-brand-blue', dot: 'bg-brand-blue', text: 'text-brand-blue' },
  // "Sin método registrado" (cobros manuales previos a P3.2, sin backfill de `method`):
  // gris neutro a propósito, NO rojo/danger — es plata real, no un error, y el gris de
  // "sin categorizar" no debe competir por atención con las identidades reales (efectivo/
  // transferencia) ni leerse como una alarma.
  neutral: { stroke: 'stroke-brand-dim', fill: 'fill-brand-dim', dot: 'bg-brand-dim', text: 'text-brand-dim' },
}

export const toneFor = (tone) => CHART_TONES[tone] || CHART_TONES.orange
