export const BRAND_ICON = '/pwa-192x192.png'
export const BRAND_WORDMARK = '/marca.png'

export const CONTACT_EMAIL = import.meta.env.VITE_CONTACT_EMAIL || 'contacto@tymroapp.com'
export const CONTACT_WHATSAPP = import.meta.env.VITE_CONTACT_WHATSAPP || ''

export const START_PRICE = import.meta.env.VITE_TYMRO_START_PRICE || ''
export const PRO_PRICE = import.meta.env.VITE_TYMRO_PRO_PRICE || ''
export const MAX_PRICE = import.meta.env.VITE_TYMRO_MAX_PRICE || ''

const normalizeWhatsapp = (value) => String(value || '').replace(/[^\d]/g, '')
const buildWhatsappUrl = (message = '') => {
  const configuredUrl = import.meta.env.VITE_SOCIAL_WHATSAPP_URL || ''
  const text = message ? `text=${encodeURIComponent(message)}` : ''

  if (configuredUrl) {
    const separator = configuredUrl.includes('?') ? '&' : '?'
    return text ? `${configuredUrl}${separator}${text}` : configuredUrl
  }

  const phone = normalizeWhatsapp(CONTACT_WHATSAPP)
  return `https://wa.me/${phone}${text ? `?${text}` : ''}`
}

export const WHATSAPP_LEAD_URL = buildWhatsappUrl('Hola, quiero conocer más sobre TYMRO.')
export const WHATSAPP_CAPACITY_URL = buildWhatsappUrl(
  'Hola, necesito más información sobre una configuración de TYMRO con mayor capacidad.',
)

export const SOCIAL_LINKS = [
  {
    id: 'whatsapp',
    label: 'WhatsApp',
    url: buildWhatsappUrl('Hola, quiero conocer más sobre TYMRO.'),
  },
  {
    id: 'instagram',
    label: 'Instagram',
    url: import.meta.env.VITE_SOCIAL_INSTAGRAM_URL || '',
  },
  {
    id: 'youtube',
    label: 'YouTube',
    url: import.meta.env.VITE_SOCIAL_YOUTUBE_URL || '',
  },
]
