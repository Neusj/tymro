import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ConfirmDialog from './ConfirmDialog'

function renderDialog(props = {}) {
  return render(
    <ConfirmDialog
      open
      title="Confirmar accion"
      description="Texto compatible anterior"
      confirmLabel="Aceptar"
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      {...props}
    />,
  )
}

describe('ConfirmDialog', () => {
  it('abre con role dialog, titulo y description backwards compatible', () => {
    renderDialog()

    expect(screen.getByRole('dialog', { name: 'Confirmar accion' })).toBeInTheDocument()
    expect(screen.getByText('Texto compatible anterior')).toBeInTheDocument()
  })

  it('usa message cuando se entrega', () => {
    renderDialog({ message: 'Nuevo mensaje', description: 'Mensaje viejo' })

    expect(screen.getByText('Nuevo mensaje')).toBeInTheDocument()
    expect(screen.queryByText('Mensaje viejo')).not.toBeInTheDocument()
  })

  it('confirma y cancela', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const user = userEvent.setup()
    renderDialog({ onConfirm, onCancel })

    await user.click(screen.getByRole('button', { name: 'Aceptar' }))
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('cierra con Escape cuando no esta loading', () => {
    const onCancel = vi.fn()
    renderDialog({ onCancel })

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('no cierra con Escape mientras esta loading', () => {
    const onCancel = vi.fn()
    renderDialog({ onCancel, loading: true })

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Procesando...' })).toBeDisabled()
  })

  it('aplica variante danger por defecto para compatibilidad visual', () => {
    renderDialog()

    expect(screen.getByRole('button', { name: 'Aceptar' })).toHaveClass('bg-brand-red')
  })

  it('aplica variante default no destructiva', () => {
    renderDialog({ variant: 'default' })

    expect(screen.getByRole('button', { name: 'Aceptar' })).toHaveClass('bg-brand-blue')
  })

  it('soporta cancelLabel configurable', () => {
    renderDialog({ cancelLabel: 'Volver' })

    expect(screen.getByRole('button', { name: 'Volver' })).toBeInTheDocument()
  })

  it('devuelve el foco al elemento que abrio el dialogo al desmontar', async () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Abrir</button>
          <ConfirmDialog
            open={open}
            title="Cerrar foco"
            message="Prueba de foco"
            confirmLabel="Aceptar"
            variant="default"
            onConfirm={() => setOpen(false)}
            onCancel={() => setOpen(false)}
          />
        </>
      )
    }

    const user = userEvent.setup()
    render(<Harness />)

    const trigger = screen.getByRole('button', { name: 'Abrir' })
    await user.click(trigger)
    await user.click(await screen.findByRole('button', { name: 'Aceptar' }))

    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
