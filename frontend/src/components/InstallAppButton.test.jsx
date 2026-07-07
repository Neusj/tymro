import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

let mockState
vi.mock('../pwa/usePwaInstall', () => ({
  default: () => mockState,
}))

import InstallAppButton from './InstallAppButton'

beforeEach(() => {
  mockState = {
    canInstall: false,
    installed: false,
    isStandalone: false,
    isIOS: false,
    promptInstall: vi.fn().mockResolvedValue('accepted'),
  }
})

describe('InstallAppButton — visibilidad', () => {
  it('se oculta cuando la app ya corre instalada (standalone)', () => {
    mockState.isStandalone = true
    mockState.canInstall = true
    const { container } = render(<InstallAppButton />)
    expect(container).toBeEmptyDOMElement()
  })

  it('se oculta cuando la app fue instalada (appinstalled)', () => {
    mockState.installed = true
    const { container } = render(<InstallAppButton />)
    expect(container).toBeEmptyDOMElement()
  })

  it('se oculta cuando no hay forma de instalar (ni prompt ni iOS)', () => {
    // Escritorio/navegador donde beforeinstallprompt no disparó: nada que ofrecer.
    const { container } = render(<InstallAppButton />)
    expect(container).toBeEmptyDOMElement()
  })

  it('aparece cuando el navegador ofreció instalar (beforeinstallprompt)', () => {
    mockState.canInstall = true
    render(<InstallAppButton />)
    expect(screen.getByRole('button', { name: /instalar app/i })).toBeInTheDocument()
  })

  it('aparece en iOS aunque no haya beforeinstallprompt', () => {
    mockState.isIOS = true
    render(<InstallAppButton />)
    expect(screen.getByRole('button', { name: /instalar app/i })).toBeInTheDocument()
  })
})

describe('InstallAppButton — acción', () => {
  it('en Android/escritorio dispara el prompt nativo y no abre modal', async () => {
    mockState.canInstall = true
    render(<InstallAppButton />)

    await userEvent.click(screen.getByRole('button', { name: /instalar app/i }))

    expect(mockState.promptInstall).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('en iOS abre el instructivo manual (Compartir → Agregar a pantalla de inicio)', async () => {
    mockState.isIOS = true
    render(<InstallAppButton />)

    await userEvent.click(screen.getByRole('button', { name: /instalar app/i }))

    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText(/compartir/i)).toBeInTheDocument()
    expect(screen.getByText(/agregar a pantalla de inicio/i)).toBeInTheDocument()
    // iOS no usa el prompt nativo.
    expect(mockState.promptInstall).not.toHaveBeenCalled()
  })

  it('el instructivo iOS se puede cerrar', async () => {
    mockState.isIOS = true
    render(<InstallAppButton />)

    await userEvent.click(screen.getByRole('button', { name: /instalar app/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /cerrar/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
