import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import FeedbackBanner from './FeedbackBanner'

describe('FeedbackBanner', () => {
  it('renderiza success, error, warning e info', () => {
    const { rerender } = render(<FeedbackBanner type="success" message="Guardado" />)
    expect(screen.getByRole('status')).toHaveTextContent('Guardado')

    rerender(<FeedbackBanner type="error" message="No se pudo guardar" />)
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo guardar')

    rerender(<FeedbackBanner type="warning" message="Revisa los datos" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Revisa los datos')

    rerender(<FeedbackBanner type="info" message="Dato informativo" />)
    expect(screen.getByRole('status')).toHaveTextContent('Dato informativo')
  })

  it('muestra titulo cuando se entrega', () => {
    render(<FeedbackBanner type="info" title="Atencion" message="Mensaje contextual" />)

    expect(screen.getByText('Atencion')).toBeInTheDocument()
    expect(screen.getByText('Mensaje contextual')).toBeInTheDocument()
  })

  it('permite descartar el mensaje', async () => {
    const onDismiss = vi.fn()
    const user = userEvent.setup()

    render(<FeedbackBanner type="success" message="Listo" onDismiss={onDismiss} />)

    await user.click(screen.getByRole('button', { name: /cerrar mensaje/i }))

    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('sin message no renderiza nada', () => {
    const { container } = render(<FeedbackBanner type="info" message="" />)
    expect(container).toBeEmptyDOMElement()
  })
})
