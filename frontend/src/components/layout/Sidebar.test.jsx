import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import Sidebar from './Sidebar'

// P3.5: se eliminó el REPORTE/LISTADO de pagos manuales (la capa 2 de Ingresos lo
// reemplaza). Este test cubre el pedido explícito de "un test sobre Sidebar verificando
// que el menú de Reportes ya no ofrece 'Pagos manuales' y sí ofrece los otros cuatro".
const renderSidebar = (user = { role: 'gym_admin' }) =>
  render(
    <MemoryRouter>
      <Sidebar isOpen isMobile user={user} onNavigate={() => {}} onRequestOpen={() => {}} />
    </MemoryRouter>,
  )

describe('Sidebar — menú de Reportes (gym_admin)', () => {
  it('ya no ofrece "Pagos manuales", y sí ofrece los otros cuatro reportes', async () => {
    renderSidebar()
    const user = userEvent.setup()

    // El grupo "Reportes" arranca colapsado (ningún link activo en la ruta de prueba);
    // hay que abrirlo para que sus hijos entren al DOM.
    await user.click(screen.getByRole('button', { name: 'Reportes' }))

    expect(screen.getByRole('link', { name: 'Ingresos' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ocupación' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Retención' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Conversión de prueba' })).toBeInTheDocument()

    expect(screen.queryByRole('link', { name: 'Pagos manuales' })).not.toBeInTheDocument()
    expect(screen.queryByText('Pagos manuales')).not.toBeInTheDocument()
  })
})

describe('Sidebar - orden de actividad personal', () => {
  it('en gym_admin muestra primero reservas, luego clases disponibles, sin recurrencias ni historial', async () => {
    renderSidebar({ role: 'gym_admin' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Mi actividad' }))

    const personalLinks = screen
      .getAllByRole('link')
      .filter((link) => ['Mis reservas', 'Clases disponibles'].includes(link.textContent))

    expect(personalLinks.map((link) => link.textContent)).toEqual(['Mis reservas', 'Clases disponibles'])
    expect(screen.queryByRole('link', { name: 'Mis recurrencias' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Historial' })).not.toBeInTheDocument()
  })

  it('en alumno muestra primero reservas, luego clases disponibles, sin recurrencias ni historial', async () => {
    renderSidebar({ role: 'student' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Mis clases' }))

    const classLinks = screen
      .getAllByRole('link')
      .filter((link) => ['Mis reservas', 'Clases disponibles'].includes(link.textContent))

    expect(classLinks.map((link) => link.textContent)).toEqual(['Mis reservas', 'Clases disponibles'])
    expect(screen.queryByRole('link', { name: 'Mis recurrencias' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Historial' })).not.toBeInTheDocument()
  })
})

describe('Sidebar — menú de profesor', () => {
  it('oculta "Mis pagos" y muestra los dos flujos docentes', async () => {
    renderSidebar({ role: 'teacher' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Clases' }))

    expect(screen.getByRole('link', { name: 'Mis clases' })).toHaveAttribute('href', '/teacher/classes/upcoming')
    expect(screen.getByRole('link', { name: 'Clases por cubrir' })).toHaveAttribute('href', '/teacher/classes/coverable')
    expect(screen.queryByRole('link', { name: 'Mis pagos' })).not.toBeInTheDocument()
    expect(screen.queryByText('Mis pagos')).not.toBeInTheDocument()
  })
})

describe('Sidebar — menú de Clases (gym_admin)', () => {
  it('ordena Mis clases, Clases por cubrir y Gestion de clases', async () => {
    renderSidebar({ role: 'gym_admin' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Clases' }))

    const classLinks = screen
      .getAllByRole('link')
      .filter((link) => ['Mis clases', 'Clases por cubrir', 'Gestión de clases'].includes(link.textContent))

    expect(classLinks.map((link) => link.textContent)).toEqual(['Mis clases', 'Clases por cubrir', 'Gestión de clases'])
    expect(screen.getByRole('link', { name: 'Mis clases' })).toHaveAttribute('href', '/teacher/classes/upcoming')
    expect(screen.getByRole('link', { name: 'Clases por cubrir' })).toHaveAttribute('href', '/teacher/classes/coverable')
    expect(screen.getByRole('link', { name: 'Gestión de clases' })).toHaveAttribute('href', '/gym-admin/class-templates')
  })
})

describe('Sidebar — flujo personal del gym_admin', () => {
  it('muestra actividad personal separada de la asignacion administrativa de planes', async () => {
    renderSidebar({ role: 'gym_admin' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Mi actividad' }))
    await user.click(screen.getByRole('button', { name: 'Planes' }))

    expect(screen.getByRole('link', { name: 'Comprar para mí' })).toHaveAttribute('href', '/student/plans/comprar')
    expect(screen.getByRole('link', { name: 'Mis membresías' })).toHaveAttribute('href', '/student/plans')
    expect(screen.getByRole('link', { name: 'Mis reservas' })).toHaveAttribute('href', '/student/classes/reservations')
    expect(screen.getByRole('link', { name: 'Asignar plan' })).toHaveAttribute('href', '/gym-admin/plans/assign')
  })
})

describe('Sidebar - configuracion de clases personalizadas', () => {
  it('muestra el acceso para activar el flujo desde la UI', async () => {
    renderSidebar({ role: 'gym_admin' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Configuraciones' }))

    expect(screen.getByRole('button', { name: 'Pagos' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: 'Comunicación' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: 'Membresías' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: 'Operación' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Clases personalizadas' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Operación' }))
    expect(screen.getByRole('link', { name: 'Clases personalizadas' })).toHaveAttribute(
      'href',
      '/gym-admin/settings/personalized-classes',
    )

    await user.click(screen.getByRole('button', { name: 'Pagos' }))
    expect(screen.getByRole('link', { name: 'MercadoPago' })).toHaveAttribute('href', '/ajustes/pagos')
  })

  it('muestra las clases personalizadas dentro de Mis clases del alumno cuando estan activadas', async () => {
    const enabledOrg = { personalized_classes_enabled: true }
    const user = userEvent.setup()

    renderSidebar({ role: 'student', organization_detail: enabledOrg })
    await user.click(screen.getByRole('button', { name: 'Mis clases' }))
    expect(screen.getByRole('link', { name: 'Clases personalizadas' })).toHaveAttribute(
      'href',
      '/student/classes/personalized',
    )
  })

  it('muestra el flujo operativo de clases personalizadas para profesores', async () => {
    renderSidebar({ role: 'teacher', organization_detail: { personalized_classes_enabled: true } })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Clases' }))

    expect(screen.getByRole('link', { name: 'Clases personalizadas' })).toHaveAttribute(
      'href',
      '/teacher/personalized-class',
    )
  })

  it('muestra el flujo operativo de clases personalizadas para admin', async () => {
    renderSidebar({ role: 'gym_admin', organization_detail: { personalized_classes_enabled: true } })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Clases' }))

    const links = screen.getAllByRole('link', { name: 'Clases personalizadas' })
    expect(links.some((link) => link.getAttribute('href') === '/teacher/personalized-class')).toBe(true)
  })
})
