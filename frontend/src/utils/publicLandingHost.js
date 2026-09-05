const normalizeHost = (host = '') => host.split(':')[0].trim().toLowerCase()

const normalizeSubdomain = (value = '') =>
  String(value)
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .split('/')[0]
    .split('.')[0]
    .replace(/[^a-z0-9-]/g, '')
    .replace(/^-+|-+$/g, '')

const normalizePathname = (pathname = '/') => {
  const value = String(pathname || '/').trim()
  return value || '/'
}

export function resolveHostnameContext({
  hostname,
  baseDomain,
  appSubdomain = 'app',
} = {}) {
  const host = normalizeHost(hostname)
  const normalizedBaseDomain = normalizeHost(baseDomain)
  const normalizedAppSubdomain = normalizeSubdomain(appSubdomain) || 'app'

  if (!host || !normalizedBaseDomain) {
    return {
      type: 'external',
      host,
      subdomain: '',
      isPublicDomain: false,
      isAdminDomain: false,
      isTenantDomain: false,
      shouldShowLoginSelector: false,
    }
  }

  if (host === normalizedBaseDomain) {
    return {
      type: 'public',
      host,
      subdomain: '',
      isPublicDomain: true,
      isAdminDomain: false,
      isTenantDomain: false,
      shouldShowLoginSelector: true,
    }
  }

  const suffix = `.${normalizedBaseDomain}`
  if (!host.endsWith(suffix)) {
    return {
      type: 'external',
      host,
      subdomain: '',
      isPublicDomain: false,
      isAdminDomain: false,
      isTenantDomain: false,
      shouldShowLoginSelector: false,
    }
  }

  const subdomain = host.slice(0, -suffix.length).split('.')[0]
  const isAdminDomain = subdomain === normalizedAppSubdomain

  return {
    type: isAdminDomain ? 'admin' : 'tenant',
    host,
    subdomain,
    isPublicDomain: false,
    isAdminDomain,
    isTenantDomain: !isAdminDomain,
    shouldShowLoginSelector: false,
  }
}

export function resolveHostnameContextForWindow(location = window.location) {
  return resolveHostnameContext({
    hostname: location?.hostname || location?.host || '',
    baseDomain: import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    appSubdomain: import.meta.env.VITE_APP_SUBDOMAIN || 'app',
  })
}

export function shouldShowPublicLanding(hostname, baseDomain, pathname = '/') {
  const context = resolveHostnameContext({ hostname, baseDomain })
  return context.isPublicDomain && normalizePathname(pathname) === '/'
}

export function shouldShowPublicLandingForWindow(location = window.location) {
  return shouldShowPublicLanding(
    location?.hostname || location?.host || '',
    import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    location?.pathname || '/',
  )
}

const appendPath = (url, path = '') => {
  const normalizedPath = String(path || '')
  if (!url || !normalizedPath) {
    return url
  }
  return `${url}${normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`}`
}

export function buildAppUrl({
  baseDomain,
  appSubdomain = 'app',
  protocol = 'https:',
  port = '',
} = {}) {
  const normalizedBaseDomain = normalizeHost(baseDomain)
  const normalizedAppSubdomain = normalizeSubdomain(appSubdomain)
  if (!normalizedBaseDomain || !normalizedAppSubdomain) {
    return ''
  }

  const normalizedProtocol = protocol || 'https:'
  const portSuffix = port ? `:${String(port).replace(/^:/, '')}` : ''
  return `${normalizedProtocol}//${normalizedAppSubdomain}.${normalizedBaseDomain}${portSuffix}`
}

export function buildAppUrlForWindow(location = window.location) {
  return buildAppUrl({
    baseDomain: import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    appSubdomain: import.meta.env.VITE_APP_SUBDOMAIN || 'app',
    protocol: location?.protocol,
    port: location?.port,
  })
}

export function buildPublicLandingUrl({
  baseDomain,
  protocol = 'https:',
  port = '',
} = {}) {
  const normalizedBaseDomain = normalizeHost(baseDomain)
  if (!normalizedBaseDomain) {
    return ''
  }

  const normalizedProtocol = protocol || 'https:'
  const portSuffix = port ? `:${String(port).replace(/^:/, '')}` : ''
  return `${normalizedProtocol}//${normalizedBaseDomain}${portSuffix}`
}

export function buildPublicLandingUrlForWindow(location = window.location) {
  return buildPublicLandingUrl({
    baseDomain: import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    protocol: location?.protocol,
    port: location?.port,
  })
}

export function buildGeneralLoginUrl({
  baseDomain,
  protocol = 'https:',
  port = '',
  path = '/login',
} = {}) {
  return appendPath(buildPublicLandingUrl({ baseDomain, protocol, port }), path)
}

export function buildGeneralLoginUrlForWindow(location = window.location) {
  return buildGeneralLoginUrl({
    baseDomain: import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    protocol: location?.protocol,
    port: location?.port,
  })
}

export function buildTenantUrl({
  baseDomain,
  subdomain,
  protocol = 'https:',
  port = '',
} = {}) {
  const normalizedBaseDomain = normalizeHost(baseDomain)
  const normalizedSubdomain = normalizeSubdomain(subdomain)
  if (!normalizedBaseDomain || !normalizedSubdomain) {
    return ''
  }

  const normalizedProtocol = protocol || 'https:'
  const portSuffix = port ? `:${String(port).replace(/^:/, '')}` : ''
  return `${normalizedProtocol}//${normalizedSubdomain}.${normalizedBaseDomain}${portSuffix}`
}

export function buildTenantUrlForWindow(subdomain, location = window.location) {
  return buildTenantUrl({
    baseDomain: import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    subdomain,
    protocol: location?.protocol,
    port: location?.port,
  })
}

export function buildTenantDisplayHost({
  baseDomain,
  subdomain,
} = {}) {
  const normalizedBaseDomain = normalizeHost(baseDomain)
  const normalizedSubdomain = normalizeSubdomain(subdomain)
  if (!normalizedBaseDomain || !normalizedSubdomain) {
    return ''
  }
  return `${normalizedSubdomain}.${normalizedBaseDomain}`
}

export function buildTenantDisplayHostForWindow(subdomain) {
  return buildTenantDisplayHost({
    baseDomain: import.meta.env.VITE_PUBLIC_BASE_DOMAIN,
    subdomain,
  })
}
