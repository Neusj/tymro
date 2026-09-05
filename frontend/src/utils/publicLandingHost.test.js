import { describe, expect, it } from 'vitest'
import {
  buildAppUrl,
  buildGeneralLoginUrl,
  buildPublicLandingUrl,
  buildTenantDisplayHost,
  buildTenantUrl,
  resolveHostnameContext,
  shouldShowPublicLanding,
} from './publicLandingHost'

describe('shouldShowPublicLanding', () => {
  it('shows the public landing only on the configured production base domain', () => {
    expect(shouldShowPublicLanding('tymroapp.com', 'tymroapp.com')).toBe(true)
    expect(shouldShowPublicLanding('app.tymroapp.com', 'tymroapp.com')).toBe(false)
    expect(shouldShowPublicLanding('gladiador.tymroapp.com', 'tymroapp.com')).toBe(false)
  })

  it('uses the configured development base domain without local host exceptions', () => {
    expect(shouldShowPublicLanding('localhost', 'localhost')).toBe(true)
    expect(shouldShowPublicLanding('app.localhost', 'localhost')).toBe(false)
    expect(shouldShowPublicLanding('gladiador.localhost', 'localhost')).toBe(false)
  })

  it('normalizes ports and casing', () => {
    expect(shouldShowPublicLanding('LOCALHOST:5173', 'localhost')).toBe(true)
    expect(shouldShowPublicLanding('TYMROAPP.COM:443', 'tymroapp.com')).toBe(true)
  })

  it('does not expose the landing when the base domain is missing', () => {
    expect(shouldShowPublicLanding('localhost', '')).toBe(false)
  })

  it('does not render the public landing for the general login route', () => {
    expect(shouldShowPublicLanding('tymroapp.com', 'tymroapp.com', '/login')).toBe(false)
  })
})

describe('resolveHostnameContext', () => {
  it('identifies the public domain as the only context with the login selector', () => {
    const context = resolveHostnameContext({ hostname: 'tymroapp.com', baseDomain: 'tymroapp.com' })
    expect(context.type).toBe('public')
    expect(context.shouldShowLoginSelector).toBe(true)
  })

  it('identifies the reserved app subdomain as admin, not tenant', () => {
    const context = resolveHostnameContext({ hostname: 'app.tymroapp.com', baseDomain: 'tymroapp.com' })
    expect(context.type).toBe('admin')
    expect(context.subdomain).toBe('app')
    expect(context.isTenantDomain).toBe(false)
    expect(context.shouldShowLoginSelector).toBe(false)
  })

  it('identifies organization subdomains as tenant contexts without selector', () => {
    const context = resolveHostnameContext({ hostname: 'gladiador.tymroapp.com', baseDomain: 'tymroapp.com' })
    expect(context.type).toBe('tenant')
    expect(context.subdomain).toBe('gladiador')
    expect(context.isTenantDomain).toBe(true)
    expect(context.shouldShowLoginSelector).toBe(false)
  })
})

describe('buildAppUrl', () => {
  it('builds the administrative app URL from the same configured base domain', () => {
    expect(buildAppUrl({ baseDomain: 'tymroapp.com', appSubdomain: 'app', protocol: 'https:' })).toBe(
      'https://app.tymroapp.com',
    )
    expect(buildAppUrl({ baseDomain: 'localhost', appSubdomain: 'app', protocol: 'http:', port: '5173' })).toBe(
      'http://app.localhost:5173',
    )
  })
})

describe('buildPublicLandingUrl', () => {
  it('builds the public landing URL from the configured base domain', () => {
    expect(buildPublicLandingUrl({ baseDomain: 'tymroapp.com', protocol: 'https:' })).toBe('https://tymroapp.com')
    expect(buildPublicLandingUrl({ baseDomain: 'localhost', protocol: 'http:', port: '5173' })).toBe(
      'http://localhost:5173',
    )
  })
})

describe('buildTenantUrl', () => {
  it('builds an organization URL from a subdomain and the configured base domain', () => {
    expect(buildTenantUrl({ baseDomain: 'tymroapp.com', subdomain: 'gladiador', protocol: 'https:' })).toBe(
      'https://gladiador.tymroapp.com',
    )
    expect(buildTenantUrl({ baseDomain: 'localhost', subdomain: 'gladiador', protocol: 'http:', port: '5173' })).toBe(
      'http://gladiador.localhost:5173',
    )
  })

  it('accepts pasted host values and keeps only the organization subdomain', () => {
    expect(buildTenantUrl({ baseDomain: 'tymroapp.com', subdomain: 'https://GLADIADOR.tymroapp.com/login' })).toBe(
      'https://gladiador.tymroapp.com',
    )
  })

  it('also builds the reserved app subdomain when typed in the center field', () => {
    expect(buildTenantUrl({ baseDomain: 'tymroapp.com', subdomain: 'app', protocol: 'https:' })).toBe(
      'https://app.tymroapp.com',
    )
  })
})

describe('buildGeneralLoginUrl', () => {
  it('builds the general login on the public domain', () => {
    expect(buildGeneralLoginUrl({ baseDomain: 'tymroapp.com', protocol: 'https:' })).toBe(
      'https://tymroapp.com/login',
    )
  })
})

describe('buildTenantDisplayHost', () => {
  it('builds the host label used by the center access hint', () => {
    expect(buildTenantDisplayHost({ baseDomain: 'tymroapp.com', subdomain: 'gladiador' })).toBe(
      'gladiador.tymroapp.com',
    )
  })
})
