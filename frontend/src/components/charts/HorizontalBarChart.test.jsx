import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
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

  // P3.5 (drilldown de Ingresos): una fila con `href` se vuelve un <Link> real, no un
  // <div> decorativo — foco de teclado real y un aria-label que nombra la categoría.
  it('una fila con href se renderiza como link accesible con aria-label propio', () => {
    render(
      <MemoryRouter>
        <HorizontalBarChart
          items={[{ label: 'MercadoPago', value: 50000, hint: 'Bruto $60.000', href: '/gym-admin/reports/revenue/mercadopago' }]}
          formatValue={(v) => `$${v}`}
        />
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: /MercadoPago: \$50000 · Bruto \$60\.000/ })
    expect(link).toHaveAttribute('href', '/gym-admin/reports/revenue/mercadopago')
  })

  // Sin href/onClick, la fila sigue siendo el <div> no interactivo de siempre — otros
  // consumidores del componente (Ocupación, Retención) no cambian en nada.
  it('una fila SIN href/onClick sigue sin ser un elemento interactivo (comportamiento previo intacto)', () => {
    render(<HorizontalBarChart items={[{ label: 'Lunes', value: 10 }]} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('una fila con onClick (sin href) se renderiza como <button> real y dispara el handler con la fila', () => {
    const handleClick = vi.fn()
    render(
      <HorizontalBarChart
        items={[{ label: 'Efectivo', value: 3000, onClick: handleClick }]}
        formatValue={(v) => `$${v}`}
      />,
    )
    const button = screen.getByRole('button', { name: /Efectivo: \$3000/ })
    fireEvent.click(button)
    expect(handleClick).toHaveBeenCalledWith(expect.objectContaining({ label: 'Efectivo', value: 3000 }))
  })
})
