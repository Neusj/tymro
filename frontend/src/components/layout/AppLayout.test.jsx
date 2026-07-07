import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AppLayout from './AppLayout'
import { AuthProvider } from '../../auth/AuthContext'

// jsdom no implementa matchMedia; AppLayout lo usa para el breakpoint móvil.
beforeAll(() => {
  window.matchMedia =
    window.matchMedia ||
    ((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }))
})

// AppLayout monta RutReminderBanner, que consume AuthContext (useAuth). En la
// app real AppLayout siempre vive bajo AuthProvider; sin token en localStorage
// el provider no hace red y user=null, así que el banner no se renderiza y estas
// pruebas del header (que leen el `user` PROP) quedan intactas.
function renderLayout(user) {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <AppLayout user={user} onLogout={() => {}}>
          <div>contenido</div>
        </AppLayout>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('AppLayout header — identidad del usuario', () => {
  it('muestra "Nombre Apellido — {role_display}" usando la etiqueta legible del backend', () => {
    renderLayout({ first_name: 'Juan', last_name: 'Pérez', role: 'gym_admin', role_display: 'Administrador' })

    expect(screen.getByText('Juan Pérez — Administrador')).toBeInTheDocument()
    // Nunca muestra la key interna del rol.
    expect(screen.queryByText(/gym_admin/)).not.toBeInTheDocument()
  })

  it('sin nombre, muestra solo el rol legible (sin em-dash colgando)', () => {
    renderLayout({ first_name: '', last_name: '', role: 'student', role_display: 'Alumno' })

    expect(screen.getByText('Alumno')).toBeInTheDocument()
    expect(screen.queryByText(/—/)).not.toBeInTheDocument()
  })

  it('con solo nombre de pila no rompe el formato', () => {
    renderLayout({ first_name: 'Juan', last_name: '', role: 'gym_admin', role_display: 'Administrador' })

    expect(screen.getByText('Juan — Administrador')).toBeInTheDocument()
  })

  it('sin usuario no revienta el layout', () => {
    renderLayout(null)

    expect(screen.getByText('contenido')).toBeInTheDocument()
  })
})
