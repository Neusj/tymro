import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import DaySelector from './DaySelector'

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

  it('abre el calendario completo y aplica una fecha lejana', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()

    render(<DaySelector value="2026-08-05" onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: 'Calendario' }))
    await user.clear(screen.getByLabelText('Fecha del calendario'))
    await user.type(screen.getByLabelText('Fecha del calendario'), '2026-12-24')
    await user.click(screen.getByRole('button', { name: 'Aplicar fecha' }))

    expect(onChange).toHaveBeenCalledWith('2026-12-24')
  })
})
