import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect } from 'vitest'

// P3.5: el drilldown de Ingresos usa /reports/revenue/:method (capa 2) y
// /reports/revenue/:kind/:id (capa 3). 'mercadopago' es a la vez un `method` válido y un
// `kind` válido, así que antes de comprometerse a esas dos formas de ruta (en vez de algo
// más explícito como /revenue/method/:method y /revenue/payment/:kind/:id) hay que probar
// que React Router las distingue por CANTIDAD de segmentos, no por el nombre del valor:
// una URL con un solo segmento después de /revenue solo puede calzar contra :method (no
// hay :id que llenar), una con dos solo contra :kind/:id. Mismas rutas EXACTAS que
// App.jsx, con componentes marcadores en vez de las páginas reales — esto es una prueba
// de resolución de rutas, no de las páginas.
function RoutesUnderTest() {
  return (
    <Routes>
      <Route path="/gym-admin/reports/revenue/:method" element={<div data-testid="layer">capa2</div>} />
      <Route path="/gym-admin/reports/revenue/:kind/:id" element={<div data-testid="layer">capa3</div>} />
    </Routes>
  )
}

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <RoutesUnderTest />
    </MemoryRouter>,
  )

describe('rutas de drilldown de Ingresos: sin colisión entre capa 2 y capa 3', () => {
  it('/revenue/mercadopago (1 segmento) cae en la capa 2, no en la 3', () => {
    renderAt('/gym-admin/reports/revenue/mercadopago')
    expect(screen.getByTestId('layer')).toHaveTextContent('capa2')
  })

  it('/revenue/mercadopago/<uuid> (2 segmentos) cae en la capa 3, no en la 2, aunque el método y el kind se llamen igual', () => {
    renderAt('/gym-admin/reports/revenue/mercadopago/3f2b1111-0000-0000-0000-000000000001')
    expect(screen.getByTestId('layer')).toHaveTextContent('capa3')
  })

  it('/revenue/cash (método manual, 1 segmento) también cae en la capa 2', () => {
    renderAt('/gym-admin/reports/revenue/cash')
    expect(screen.getByTestId('layer')).toHaveTextContent('capa2')
  })

  it('/revenue/manual/123 (kind manual + id numérico, 2 segmentos) cae en la capa 3', () => {
    renderAt('/gym-admin/reports/revenue/manual/123')
    expect(screen.getByTestId('layer')).toHaveTextContent('capa3')
  })
})
