import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import HorizontalBarChart from './HorizontalBarChart'

describe('HorizontalBarChart', () => {
  it('sin items muestra el estado vacío explícito', () => {
    render(<HorizontalBarChart items={[]} />)
    expect(screen.getByText('Sin datos en el período.')).toBeInTheDocument()
  })

  it('con un solo item no revienta y muestra su valor', () => {
    render(<HorizontalBarChart items={[{ label: 'Efectivo', value: 5000 }]} formatValue={(v) => `$${v}`} />)
    expect(screen.getByText('Efectivo')).toBeInTheDocument()
    expect(screen.getByText('$5000')).toBeInTheDocument()
  })

  it('con todos los valores en 0 no revienta (barras en 0%, sin división por cero)', () => {
    const { container } = render(
      <HorizontalBarChart
        items={[
          { label: 'Efectivo', value: 0 },
          { label: 'Transferencia', value: 0 },
        ]}
      />,
    )
    const rects = container.querySelectorAll('rect')
    expect(rects).toHaveLength(2)
    rects.forEach((rect) => {
      expect(rect.getAttribute('width')).not.toContain('NaN')
    })
  })
})
