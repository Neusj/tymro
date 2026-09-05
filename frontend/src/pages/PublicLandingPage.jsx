import { useEffect, useMemo, useState } from 'react'
import {
  BRAND_ICON,
  BRAND_WORDMARK,
  CONTACT_EMAIL,
  MAX_PRICE,
  PRO_PRICE,
  SOCIAL_LINKS,
  START_PRICE,
  WHATSAPP_CAPACITY_URL,
  WHATSAPP_LEAD_URL,
} from '../config/publicLanding'
import { buildGeneralLoginUrlForWindow } from '../utils/publicLandingHost'

const navItems = [
  { href: '#soluciones', label: 'Soluciones' },
  { href: '#planes', label: 'Planes' },
  { href: '#faq', label: 'FAQ' },
  { href: '#contacto', label: 'Contacto' },
]

const audiences = [
  {
    id: 'centros',
    label: 'Centros deportivos',
    title: 'Control operativo para tu centro con alumnos, staff, sedes y reservas.',
    detail:
      'Ordena clases, planes, pagos, asistencia y equipo en una experiencia simple para operar mejor cada día.',
    stats: [
      ['Clases', 'Agenda, cupos y reservas bajo control.'],
      ['Planes', 'Membresías claras para cada alumno.'],
      ['Equipo', 'Roles, staff y sedes bien coordinados.'],
    ],
  },
  {
    id: 'coach',
    label: 'Coach',
    title: 'Un espacio preparado para entrenadores que crecen con su método.',
    detail:
      'Haz crecer tu método, organiza a tus clientes y dedica más tiempo a entrenar que a administrar.',
    stats: [
      ['Clientes', 'Tu comunidad en un solo lugar.'],
      ['Rutinas', 'Planifica y haz seguimiento.'],
      ['Agenda', 'Tu tiempo, bajo control.'],
    ],
  },
  {
    id: 'personal',
    label: 'Personal / familiar',
    title: 'Tu entrenamiento, tus objetivos y tu progreso en un solo lugar.',
    detail:
      'Entrena a tu ritmo, sigue tus logros y comparte retos con quienes más quieres.',
    stats: [
      ['Objetivos', 'Define hacia donde vas.'],
      ['Progreso', 'Mira cuanto has avanzado.'],
      ['Familia', 'Compartan retos y logros.'],
    ],
  },
]

const coreFeatures = [
  { title: 'Alumnos y membresías', detail: 'Perfiles, estados, beneficios y consumo de clases.', tone: 'orange' },
  { title: 'Clases y reservas', detail: 'Horarios, cupos, inscripciones, cancelaciones y sedes.', tone: 'red' },
  { title: 'Asistencia QR', detail: 'Check-in simple para alumnos, profesores y pantallas públicas.', tone: 'orange' },
  { title: 'Pagos y reportes', detail: 'Estados de pago, ingresos, ocupación, retención y conversión.', tone: 'blue' },
]

const addOns = [
  {
    title: 'Asistente comercial inteligente',
    status: 'Próximamente',
    description: 'Pensado para seguimiento comercial, prospectos, recuperación de pagos y atención automatizada.',
  },
  {
    title: 'Rutinas',
    status: 'Próximamente',
    description: 'Una forma más simple de planificar, entregar y seguir entrenamientos.',
  },
  {
    title: 'Salud y nutrición',
    status: 'Próximamente',
    description: 'Información complementaria para acompañar mejor el proceso de cada alumno.',
  },
  {
    title: 'Analítica avanzada',
    status: 'En evolución',
    description: 'Métricas profundas, tendencias y comparaciones para decidir con más claridad.',
  },
]

const planPrices = {
  Start: START_PRICE,
  Pro: PRO_PRICE,
  Max: MAX_PRICE,
}

const plans = [
  {
    name: 'Start',
    detail: 'Para centros que ordenan su operación base.',
    rows: ['hasta 150', 'hasta 15', '1', 'incluido', 'incluido', 'adicionales'],
  },
  {
    name: 'Pro',
    detail: 'El punto de equilibrio para crecer con más capacidad y una solución incluida.',
    featured: true,
    rows: ['hasta 300', 'hasta 30', 'hasta 2', 'incluido', 'incluido', '1 incluida'],
  },
  {
    name: 'Max',
    detail: 'Para operaciones con más sedes, equipo y volumen.',
    rows: ['hasta 600', 'hasta 50', 'hasta 5', 'incluido', 'incluido', 'hasta 2 incluidas'],
  },
]

const planRows = ['Alumnos', 'Staff', 'Sucursales', 'Branding propio', 'Núcleo TYMRO', 'Soluciones adicionales']

const faqs = [
  ['¿Dónde ingresan los usuarios personales o coach?', 'Desde el login general de TYMRO, separado de los subdominios de organizaciones.'],
  ['¿Dónde ingresa un centro deportivo?', 'Cada organización usa su subdominio, por ejemplo gladiador.tymroapp.com.'],
  ['¿TYMRO funciona desde el teléfono?', 'Sí. La experiencia está preparada para navegador móvil y uso como app instalable.'],
  ['¿Puedo usar varias sucursales?', 'Sí. La capacidad depende del plan contratado.'],
]

function BrandLockup({ large = false, iconOnly = false }) {
  return (
    <span className={`brand-lockup ${large ? 'brand-lockup-large' : ''} ${iconOnly ? 'brand-lockup-icon-only' : ''}`}>
      <img src={BRAND_ICON} alt="" className="brand-lockup-icon" width={large ? 64 : 36} height={large ? 64 : 36} />
      {iconOnly ? null : (
        <img src={BRAND_WORDMARK} alt="TYMRO" className="brand-lockup-wordmark" width={large ? 210 : 118} height={large ? 70 : 39} />
      )}
    </span>
  )
}

function OfficialWordmark({ className = '' }) {
  return (
    <img
      src={BRAND_WORDMARK}
      alt="TYMRO"
      className={`official-wordmark ${className}`}
      width="1086"
      height="362"
    />
  )
}

function LoginIcon() {
  return (
    <svg className="btn-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M10.8 17.2 16 12l-5.2-5.2-1.1 1.1 3.3 3.3H3.5v1.6H13l-3.3 3.3 1.1 1.1ZM19 3.5h-5.2v1.7H19c.5 0 .8.3.8.8v12c0 .5-.3.8-.8.8h-5.2v1.7H19c1.4 0 2.5-1.1 2.5-2.5V6c0-1.4-1.1-2.5-2.5-2.5Z" />
    </svg>
  )
}

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 5h15A2.5 2.5 0 0 1 22 7.5v9a2.5 2.5 0 0 1-2.5 2.5h-15A2.5 2.5 0 0 1 2 16.5v-9A2.5 2.5 0 0 1 4.5 5Zm0 2a.5.5 0 0 0-.5.5v.4l8 4.8 8-4.8v-.4a.5.5 0 0 0-.5-.5h-15Zm15 10a.5.5 0 0 0 .5-.5V10l-8 4.8L4 10v6.5a.5.5 0 0 0 .5.5h15Z" />
    </svg>
  )
}

function LandingHeader({ loginUrl }) {
  const [open, setOpen] = useState(false)
  const closeMenu = () => setOpen(false)

  return (
    <header className="landing-header">
      <a href="#inicio" className="landing-brand-link" onClick={closeMenu} aria-label="TYMRO inicio">
        <BrandLockup iconOnly />
      </a>

      <nav className="hidden items-center gap-1 md:flex" aria-label="Secciones">
        {navItems.map((item) => (
          <a key={item.href} href={item.href} className="landing-nav-link">
            {item.label}
          </a>
        ))}
      </nav>

      <div className="hidden items-center gap-3 md:flex">
        <a href={loginUrl} className="btn-ghost">
          <LoginIcon />
          Ingresar
        </a>
      </div>

      <button
        type="button"
        className="landing-menu-button"
        aria-label={open ? 'Cerrar menú' : 'Abrir menú'}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span aria-hidden="true">{open ? 'x' : '☰'}</span>
      </button>

      <div className={`landing-mobile-menu ${open ? 'is-open' : ''}`}>
        {navItems.map((item) => (
          <a key={item.href} href={item.href} className="landing-mobile-link" onClick={closeMenu}>
            {item.label}
          </a>
        ))}
        <div className="grid gap-3 pt-2">
          <a href={loginUrl} className="btn-ghost w-full" onClick={closeMenu}>
            <LoginIcon />
            Ingresar
          </a>
        </div>
      </div>
    </header>
  )
}

function HeroBrandVisual() {
  return (
    <div className="hero-brand-visual reveal" aria-label="Marca oficial TYMRO">
      <div className="hero-brand-aura" aria-hidden="true" />
      {/* Future product media slot: keep this stage stable for short feature videos,
          brief demos, and transitions between real TYMRO product views. */}
      <div className="hero-brand-stage">
        <OfficialWordmark className="hero-wordmark" />
        <div className="hero-brand-shadow" aria-hidden="true" />
      </div>
    </div>
  )
}

function SectionHeading({ eyebrow, title, children }) {
  return (
    <div className="section-heading reveal">
      <p>{eyebrow}</p>
      <h2>{title}</h2>
      {children ? <span>{children}</span> : null}
    </div>
  )
}

function PlanPrice({ value }) {
  const cleanValue = String(value || '').trim()

  if (!cleanValue) {
    return null
  }

  const formattedPrice = /^\d+$/.test(cleanValue)
    ? new Intl.NumberFormat('es-CL', {
        style: 'currency',
        currency: 'CLP',
        maximumFractionDigits: 0,
      }).format(Number(cleanValue))
    : cleanValue

  return (
    <p className="landing-plan-price">
      {formattedPrice}
      <span>/ mes</span>
    </p>
  )
}

function SocialIcon({ id }) {
  if (id === 'whatsapp') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M19.1 4.9A9.8 9.8 0 0 0 3.6 16.7L2.4 21.2l4.6-1.2A9.8 9.8 0 0 0 21.8 11.5a9.7 9.7 0 0 0-2.7-6.6Zm-7.1 14a7.4 7.4 0 0 1-3.8-1l-.3-.2-2.7.7.7-2.6-.2-.3a7.4 7.4 0 1 1 6.3 3.4Zm4.1-5.5c-.2-.1-1.3-.6-1.5-.7-.2-.1-.4-.1-.5.1l-.7.9c-.1.2-.3.2-.5.1a6 6 0 0 1-3-2.6c-.2-.3 0-.4.1-.6l.4-.4c.1-.1.1-.3.2-.4v-.4l-.7-1.7c-.2-.4-.4-.4-.5-.4h-.5c-.2 0-.4.1-.6.3-.2.2-.8.8-.8 1.9s.8 2.2.9 2.3a8.5 8.5 0 0 0 3.3 3.1c1.2.5 1.7.6 2.3.5.7-.1 1.3-.5 1.5-1 .2-.5.2-.9.1-1Z" />
      </svg>
    )
  }

  if (id === 'instagram') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M7.5 2.8h9A4.7 4.7 0 0 1 21.2 7.5v9a4.7 4.7 0 0 1-4.7 4.7h-9a4.7 4.7 0 0 1-4.7-4.7v-9A4.7 4.7 0 0 1 7.5 2.8Zm0 1.8a2.9 2.9 0 0 0-2.9 2.9v9a2.9 2.9 0 0 0 2.9 2.9h9a2.9 2.9 0 0 0 2.9-2.9v-9a2.9 2.9 0 0 0-2.9-2.9h-9Zm4.5 3.2a4.2 4.2 0 1 1 0 8.4 4.2 4.2 0 0 1 0-8.4Zm0 1.8a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8Zm4.4-2.9a1.1 1.1 0 1 1 0 2.2 1.1 1.1 0 0 1 0-2.2Z" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M21.6 7.2a3 3 0 0 0-2.1-2.1C17.6 4.6 12 4.6 12 4.6s-5.6 0-7.5.5a3 3 0 0 0-2.1 2.1A31 31 0 0 0 1.9 12a31 31 0 0 0 .5 4.8 3 3 0 0 0 2.1 2.1c1.9.5 7.5.5 7.5.5s5.6 0 7.5-.5a3 3 0 0 0 2.1-2.1 31 31 0 0 0 .5-4.8 31 31 0 0 0-.5-4.8ZM10 15.4V8.6l5.8 3.4L10 15.4Z" />
    </svg>
  )
}

function SocialLinks() {
  return (
    <div className="landing-social-links" aria-label="Redes sociales">
      {SOCIAL_LINKS.map((item) =>
        item.url ? (
          <a key={item.id} href={item.url} aria-label={item.label} target="_blank" rel="noreferrer">
            <SocialIcon id={item.id} />
          </a>
        ) : (
          <span key={item.id} aria-label={`${item.label} pendiente de configurar`} aria-disabled="true">
            <SocialIcon id={item.id} />
          </span>
        ),
      )}
    </div>
  )
}

export default function PublicLandingPage() {
  const loginUrl = useMemo(() => buildGeneralLoginUrlForWindow() || '/login', [])
  const [audience, setAudience] = useState(audiences[0].id)
  const activeAudience = audiences.find((item) => item.id === audience) || audiences[0]

  useEffect(() => {
    const elements = Array.from(document.querySelectorAll('.reveal'))
    if (!('IntersectionObserver' in window)) {
      elements.forEach((element) => element.classList.add('is-visible'))
      return undefined
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.14, rootMargin: '0px 0px -10% 0px' },
    )

    elements.forEach((element) => observer.observe(element))
    return () => observer.disconnect()
  }, [])

  return (
    <main id="inicio" className="landing-page">
      <LandingHeader loginUrl={loginUrl} />

      <section className="landing-hero">
        <div className="landing-container landing-hero-grid">
          <div className="reveal">
            <h1 className="landing-hero-title">Entrena, conecta y crece a tu manera.</h1>
            <p className="landing-hero-copy">
              Todo tu movimiento, en un solo lugar.
            </p>
          </div>
          <HeroBrandVisual />
        </div>
      </section>

      <section id="soluciones" className="landing-section">
        <div className="landing-container">
          <SectionHeading eyebrow="Soluciones" title="Pensado para cada forma de entrenar">
            Una experiencia clara para operar un centro, acompañar clientes o sostener objetivos personales.
          </SectionHeading>

          <div className="landing-tabs reveal" role="tablist" aria-label="Tipos de usuario">
            <span className={`landing-tab-indicator active-${audience}`} aria-hidden="true" />
            {audiences.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={item.id === audience}
                className={item.id === audience ? 'is-active' : ''}
                onClick={() => setAudience(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <article key={activeAudience.id} className="landing-audience-panel reveal is-visible">
            <div>
              <p className="landing-panel-kicker">{activeAudience.label}</p>
              <h3>{activeAudience.title}</h3>
              <p>{activeAudience.detail}</p>
            </div>
            <div className="landing-audience-stats">
              {activeAudience.stats.map(([label, value], index) => (
                <div key={label} style={{ animationDelay: `${index * 70}ms` }}>
                  <strong>{label}</strong>
                  <span>{value}</span>
                </div>
              ))}
            </div>
          </article>

          <div className="landing-feature-grid">
            {coreFeatures.map((feature, index) => (
              <article key={feature.title} className={`landing-feature-card reveal tone-${feature.tone}`} style={{ transitionDelay: `${index * 45}ms` }}>
                <span className="landing-feature-icon" aria-hidden="true" />
                <h3>{feature.title}</h3>
                <p>{feature.detail}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="landing-section">
        <div className="landing-container">
          <SectionHeading eyebrow="Módulos" title="Soluciones adicionales">
            Capacidades para ampliar la experiencia sin perder foco operativo.
          </SectionHeading>
          <div className="landing-addon-grid">
            {addOns.map((addon, index) => (
              <article key={addon.title} className="landing-addon-card reveal" style={{ transitionDelay: `${index * 55}ms` }}>
                <div>
                  <h3>{addon.title}</h3>
                  <span>{addon.status}</span>
                </div>
                <p>{addon.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="planes" className="landing-section">
        <div className="landing-container">
          <SectionHeading eyebrow="Planes" title="Capacidad clara para cada etapa">
            Tres planes públicos para centros deportivos. Pro queda destacado como alternativa recomendada y equilibrada.
          </SectionHeading>
          <div className="landing-plan-grid">
            {plans.map((plan) => (
              <div key={plan.name} className={`landing-plan-shell ${plan.featured ? 'is-featured' : ''}`}>
                {plan.featured ? <span className="landing-plan-ribbon">Recomendado · Equilibrado</span> : null}
                <article className={`landing-plan-card reveal tone-${plan.name.toLowerCase()} ${plan.featured ? 'is-featured' : ''}`}>
                  <div>
                    <p className="landing-plan-kicker">Plan</p>
                    <h3>{plan.name}</h3>
                    <PlanPrice value={planPrices[plan.name]} />
                    <p>{plan.detail}</p>
                  </div>
                  <dl>
                    {planRows.map((label, index) => (
                      <div key={label} className="landing-plan-row">
                        <dt>{label}</dt>
                        <dd>{plan.rows[index]}</dd>
                      </div>
                    ))}
                  </dl>
                </article>
              </div>
            ))}
          </div>
          <div className="landing-capacity-cta reveal">
            <div>
              <h3>¿Necesitas más capacidad?</h3>
              <p>
                <a href={WHATSAPP_CAPACITY_URL} target="_blank" rel="noreferrer">
                  Contáctanos
                </a>
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="faq" className="landing-section">
        <div className="landing-container">
          <SectionHeading eyebrow="FAQ" title="Preguntas frecuentes" />
          <div className="mx-auto grid max-w-4xl gap-3">
            {faqs.map(([question, answer]) => (
              <details key={question} className="landing-faq reveal">
                <summary>{question}</summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section id="contacto" className="landing-section pb-0">
        <div className="landing-container">
          <div className="landing-final-cta reveal">
            <OfficialWordmark />
            <h2>Todo lo que necesitas para mover tu centro desde un solo lugar.</h2>
            <p>Conecta a tu equipo, ordena tu operación y prepara el crecimiento con una experiencia simple, moderna y lista para evolucionar.</p>
            <a href={WHATSAPP_LEAD_URL} className="btn-accent" target="_blank" rel="noreferrer">
              Quiero conocer TYMRO
            </a>
          </div>
        </div>

        <footer className="landing-footer reveal">
          <div className="landing-container">
            <div className="landing-footer-contact">
              <p>Contacto</p>
              <a href={`mailto:${CONTACT_EMAIL}`} aria-label={`Email ${CONTACT_EMAIL}`}>
                <MailIcon />
                <span>{CONTACT_EMAIL}</span>
              </a>
              <SocialLinks />
            </div>
          </div>
          <span className="landing-footer-copy">© TYMRO 2026</span>
          <span className="landing-footer-line" aria-hidden="true" />
        </footer>
      </section>
    </main>
  )
}
