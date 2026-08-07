import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DaySelector from './DaySelector'

const originalShowPicker = HTMLInputElement.prototype.showPicker

afterEach(() => {
  if (originalShowPicker) {
    HTMLInputElement.prototype.showPicker = originalShowPicker
  } else {
    delete HTMLInputElement.prototype.showPicker
  }
})

describe('DaySelector', () => {
  it('permite elegir otro dia de la tira semanal', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()

    render(<DaySelector value="2026-08-05" onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: 'Seleccionar 2026-08-06' }))

    expect(onChange).toHaveBeenCalledWith('2026-08-06')
  })

  it('navega entre semanas con las flechas', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()

    render(<DaySelector value="2026-08-05" onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: 'Semana siguiente' }))
    await user.click(screen.getByRole('button', { name: 'Semana anterior' }))

    expect(onChange).toHaveBeenNthCalledWith(1, '2026-08-12')
    expect(onChange).toHaveBeenNthCalledWith(2, '2026-07-29')
  })

  it('abre el calendario completo desde el boton y aplica la fecha elegida al instante', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const showPicker = vi.fn()
    HTMLInputElement.prototype.showPicker = showPicker

    render(<DaySelector value="2026-08-05" onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: 'Calendario' }))
    expect(showPicker).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByLabelText('Fecha del calendario'), { target: { value: '2026-12-24' } })

    expect(onChange).toHaveBeenCalledWith('2026-12-24')
    expect(screen.queryByRole('button', { name: 'Aplicar fecha' })).not.toBeInTheDocument()
  })
})
