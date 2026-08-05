import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import MembershipExpiryBanner from './MembershipExpiryBanner'

// El backend decide CUÁNDO mostrar el aviso (`show_expiry_banner`) y REDACTA el texto
// (`expiry_alert_message`); el front solo filtra por el flag y pinta. Nada de umbrales
// ni comparación de fechas de este lado (regla dura del CLAUDE.md de frontend).
describe('MembershipExpiryBanner', () => {
  it('con show_expiry_banner true, muestra el mensaje que manda el backend', () => {
    render(
      <MembershipExpiryBanner
        memberships={[
          {
            id: 1,
            plan_name: 'Plan Mensual',
            show_expiry_banner: true,
            days_to_expiry: 2,
            expiry_alert_level: 'danger',
            expiry_alert_message: 'Tu membresía vence en 2 días.',
            end_date: '2026-08-07',
          },
        ]}
      />,
    )

    expect(screen.getByText('Tu membresía vence en 2 días.')).toBeInTheDocument()
    expect(screen.getByText('Plan Mensual')).toBeInTheDocument()
  })

  it('con show_expiry_banner false, no renderiza nada', () => {
    const { container } = render(
      <MembershipExpiryBanner
        memberships={[
          {
            id: 1,
            plan_name: 'Plan Mensual',
            show_expiry_banner: false,
            days_to_expiry: 40,
            expiry_alert_level: 'safe',
            expiry_alert_message: 'Todo en orden.',
            end_date: '2026-09-15',
          },
        ]}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('sin membresías (o sin el prop), no renderiza nada', () => {
    const { container } = render(<MembershipExpiryBanner memberships={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('con DOS membresías con el flag encendido, muestra ambas distinguibles por nombre de plan', () => {
    render(
      <MembershipExpiryBanner
        memberships={[
          {
            id: 1,
            plan_name: 'Plan Mensual',
            show_expiry_banner: true,
            days_to_expiry: 2,
            expiry_alert_level: 'danger',
            expiry_alert_message: 'Tu membresía Plan Mensual vence en 2 días.',
            end_date: '2026-08-07',
          },
          {
            id: 2,
            plan_name: 'Plan Crossfit',
            show_expiry_banner: true,
            days_to_expiry: 5,
            expiry_alert_level: 'warning',
            expiry_alert_message: 'Tu membresía Plan Crossfit vence en 5 días.',
            end_date: '2026-08-10',
          },
          {
            id: 3,
            plan_name: 'Plan Sin aviso',
            show_expiry_banner: false,
            days_to_expiry: 90,
            expiry_alert_level: 'safe',
            expiry_alert_message: 'Todo en orden.',
            end_date: '2026-12-01',
          },
        ]}
      />,
    )

    expect(screen.getByText('Plan Mensual')).toBeInTheDocument()
    expect(screen.getByText('Plan Crossfit')).toBeInTheDocument()
    expect(screen.getByText('Tu membresía Plan Mensual vence en 2 días.')).toBeInTheDocument()
    expect(screen.getByText('Tu membresía Plan Crossfit vence en 5 días.')).toBeInTheDocument()
    // La tercera membresía (flag apagado) no debe colarse.
    expect(screen.queryByText('Plan Sin aviso')).not.toBeInTheDocument()
    expect(screen.getAllByRole('alert')).toHaveLength(2)
  })
})
