import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import PlanAlertBadge from './PlanAlertBadge'

// Sustituye a utils/planAlerts.js, que además de pintar RE-DERIVABA el estado: tenía su
// propia copia de los umbrales 5/12 y su propio vocabulario ('No vigente', 'Vigente').
// Acá solo queda color = f(nivel); el texto lo manda el backend.
describe('PlanAlertBadge', () => {
  it('muestra el mensaje que viene del backend, sin reescribirlo', () => {
    render(<PlanAlertBadge level="danger" message="Sin clases disponibles" />)

    expect(screen.getByText('Sin clases disponibles')).toBeInTheDocument()
  })

  it('pinta en rojo lo que bloquea al alumno', () => {
    render(<PlanAlertBadge level="danger" message="Matrícula impaga" />)

    expect(screen.getByText('Matrícula impaga')).toHaveClass('text-red-200')
  })

  it('pinta en rojo lo vencido', () => {
    render(<PlanAlertBadge level="expired" message="Vencido" />)

    expect(screen.getByText('Vencido')).toHaveClass('text-red-200')
  })

  it('pinta en ámbar la advertencia de vencimiento', () => {
    render(<PlanAlertBadge level="warning" message="8 dias vigentes" />)

    expect(screen.getByText('8 dias vigentes')).toHaveClass('text-amber-200')
  })

  it('pinta en verde el plan sano', () => {
    render(<PlanAlertBadge level="safe" message="20 dias vigentes" />)

    expect(screen.getByText('20 dias vigentes')).toHaveClass('text-emerald-200')
  })

  it('cae a neutro con un nivel desconocido en vez de romperse', () => {
    render(<PlanAlertBadge level="nivel-que-no-existe" message="Algo" />)

    expect(screen.getByText('Algo')).toHaveClass('text-brand-muted')
  })

  it('no renderiza nada sin mensaje', () => {
    const { container } = render(<PlanAlertBadge level="safe" message="" />)

    expect(container).toBeEmptyDOMElement()
  })
})
