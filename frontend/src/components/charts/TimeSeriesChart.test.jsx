import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TimeSeriesChart from './TimeSeriesChart'

const SERIES = [
  { key: 'net', label: 'Neto', tone: 'success' },
  { key: 'gross', label: 'Bruto', tone: 'info' },
]

describe('TimeSeriesChart', () => {
  it('con serie vacía muestra el estado vacío explícito y no revienta', () => {
    render(<TimeSeriesChart data={[]} series={SERIES} />)
    expect(screen.getByText('Sin datos en el período.')).toBeInTheDocument()
  })

  it('con data pero sin series definidas también cae al estado vacío', () => {
    render(<TimeSeriesChart data={[{ bucket: '2026-08-01', net: 100 }]} series={[]} />)
    expect(screen.getByText('Sin datos en el período.')).toBeInTheDocument()
  })

  it('con un solo punto no revienta: dibuja el punto sin línea (sin legend box de una sola serie)', () => {
    const { container } = render(
      <TimeSeriesChart
        data={[{ bucket: '2026-08-01', net: 5000 }]}
        series={[{ key: 'net', label: 'Neto', tone: 'success' }]}
        formatValue={(v) => `$${v}`}
      />,
    )
    // Un solo punto: no hay <path> de línea (un solo comando M no pinta nada), pero el
    // punto sí existe como marca visible + hit target.
    expect(container.querySelectorAll('path')).toHaveLength(0)
    expect(container.querySelectorAll('circle').length).toBeGreaterThan(0)
    // Serie única: sin legend box (el título ya la nombra).
    expect(screen.queryByText('Neto')).not.toBeInTheDocument()
  })

  it('con todos los valores en 0 no revienta (dominio no colapsa a NaN)', () => {
    const { container } = render(
      <TimeSeriesChart
        data={[
          { bucket: '2026-08-01', net: 0, gross: 0 },
          { bucket: '2026-08-02', net: 0, gross: 0 },
        ]}
        series={SERIES}
      />,
    )
    expect(container.querySelectorAll('circle').length).toBeGreaterThan(0)
    // Ningún atributo numérico del SVG debe ser NaN.
    container.querySelectorAll('circle, path, line').forEach((el) => {
      ;['cx', 'cy', 'r', 'd'].forEach((attr) => {
        const value = el.getAttribute(attr)
        expect(value === null || !value.includes('NaN')).toBe(true)
      })
    })
  })

  it('con 2+ series muestra la leyenda con las etiquetas de cada una', () => {
    render(
      <TimeSeriesChart
        data={[
          { bucket: '2026-08-01', net: 100, gross: 150 },
          { bucket: '2026-08-02', net: 200, gross: 260 },
        ]}
        series={SERIES}
      />,
    )
    expect(screen.getByText('Neto')).toBeInTheDocument()
    expect(screen.getByText('Bruto')).toBeInTheDocument()
  })
})
