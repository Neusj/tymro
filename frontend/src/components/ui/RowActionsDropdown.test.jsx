import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RowActionsDropdown from './RowActionsDropdown'

function rect({ left, top, width, height }) {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => {},
  }
}

function getMenu() {
  return screen.getByRole('button', { name: 'Eliminar' }).closest('.fixed')
}

describe('RowActionsDropdown', () => {
  let triggerRect
  let originalGetBoundingClientRect

  beforeEach(() => {
    triggerRect = rect({ left: 300, top: 100, width: 32, height: 32 })
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 480 })
    window.requestAnimationFrame = (callback) => {
      callback()
      return 1
    }

    originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
      if (this.getAttribute?.('aria-label') === 'Abrir acciones') {
        return triggerRect
      }
      if (String(this.className || '').includes('z-[1200]')) {
        return rect({ left: 0, top: 0, width: 176, height: 120 })
      }
      return originalGetBoundingClientRect.call(this)
    }
  })

  afterEach(() => {
    HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect
    vi.restoreAllMocks()
  })

  it('clampa el menu dentro del viewport en ancho movil', async () => {
    render(
      <RowActionsDropdown>
        <button type="button">Eliminar</button>
      </RowActionsDropdown>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Abrir acciones' }))

    await waitFor(() => expect(Number.parseFloat(getMenu().style.left)).toBeLessThanOrEqual(136))
    expect(Number.parseFloat(getMenu().style.left)).toBeGreaterThanOrEqual(8)
  })

  it('abre hacia arriba cuando no hay espacio bajo el trigger', async () => {
    triggerRect = rect({ left: 120, top: 440, width: 32, height: 32 })
    render(
      <RowActionsDropdown>
        <button type="button">Eliminar</button>
      </RowActionsDropdown>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Abrir acciones' }))

    await waitFor(() => expect(Number.parseFloat(getMenu().style.top)).toBeLessThan(triggerRect.top))
  })

  it('recalcula posicion despues de scroll', async () => {
    triggerRect = rect({ left: 20, top: 100, width: 32, height: 32 })
    render(
      <RowActionsDropdown>
        <button type="button">Eliminar</button>
      </RowActionsDropdown>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Abrir acciones' }))
    await waitFor(() => expect(Number.parseFloat(getMenu().style.left)).toBe(8))

    triggerRect = rect({ left: 260, top: 100, width: 32, height: 32 })
    fireEvent.scroll(window)

    await waitFor(() => expect(Number.parseFloat(getMenu().style.left)).toBe(116))
  })
})
