import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ConfirmWithReasonDialog from './ConfirmWithReasonDialog'

function renderDialog(props = {}) {
  return render(
    <ConfirmWithReasonDialog
      open
      title="Cancelar clase"
      message="Esta accion requiere un motivo."
      reasonLabel="Motivo"
      placeholder="Describe el motivo"
      confirmLabel="Confirmar"
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
      {...props}
    />,
  )
}

describe('ConfirmWithReasonDialog', () => {
  it('abre con foco inicial en el textarea', async () => {
    renderDialog()

    const reason = await screen.findByLabelText(/motivo/i)
    expect(reason).toHaveFocus()
  })

  it('bloquea confirmacion si el motivo es obligatorio y esta vacio', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    renderDialog({ onConfirm })

    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(onConfirm).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Ingresa un motivo para continuar.')
  })

  it('confirma con motivo normalizado', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    renderDialog({ onConfirm })

    await user.type(screen.getByLabelText(/motivo/i), '  Sin profesor disponible  ')
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(onConfirm).toHaveBeenCalledWith('Sin profesor disponible')
  })

  it('permite motivo opcional vacio', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    renderDialog({ onConfirm, reasonRequired: false })

    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(onConfirm).toHaveBeenCalledWith('')
  })

  it('cancela con boton y con Escape cuando no esta loading', async () => {
    const onCancel = vi.fn()
    const user = userEvent.setup()
    renderDialog({ onCancel })

    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    fireEvent.keyDown(window, { key: 'Escape' })

    expect(onCancel).toHaveBeenCalledTimes(2)
  })

  it('no cancela con Escape durante loading y deshabilita confirmar', () => {
    const onCancel = vi.fn()
    renderDialog({ onCancel, loading: true })

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Procesando...' })).toBeDisabled()
  })

  it('muestra error externo local al dialogo', () => {
    renderDialog({ error: 'No se pudo completar la accion.' })

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo completar la accion.')
  })
})
