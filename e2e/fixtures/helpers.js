import { expect } from '@playwright/test'

// En la DataTable de escritorio las acciones viven en un dropdown "Abrir acciones"
// (portal a nivel body). Abre el de la fila `rowName` y hace click en `actionName`.
export async function openRowAction(page, rowName, actionName) {
  const row = page.getByRole('row', { name: rowName })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: 'Abrir acciones' }).click()
  await page.getByRole('button', { name: actionName, exact: true }).click()
}

// Selecciona una opción en un FilterDropdown ("Profesor:", "Disciplina:", "Estado:").
export async function selectFilter(page, label, optionLabel) {
  await page.getByRole('button', { name: new RegExp(`^${label}:`) }).click()
  await page.getByRole('button', { name: optionLabel, exact: true }).click()
}

// Filtra la DataTable por texto (buscador "Buscar...") para traer una fila concreta
// a la vista, independiente de la paginación (la tabla pagina de a 10). Úsalo antes de
// openRowAction cuando la clase puede no estar en la primera página.
export async function searchClass(page, name) {
  const box = page.getByPlaceholder('Buscar...')
  await box.fill('')
  await box.fill(name)
}

// Lee el saldo "Te quedan N clases" del encabezado de Clases disponibles.
export async function getRemaining(page) {
  const badge = page.getByText(/^\d+\s+clases$/).first()
  await expect(badge).toBeVisible()
  const m = (await badge.innerText()).match(/(\d+)/)
  return m ? Number(m[1]) : null
}
