import { resolveMediaUrl } from '../api/client'

export default function Avatar({ src, alt, name, size = 'md' }) {
  const initials = (name || alt || '?')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  const sizeClass = {
    sm: 'h-8 w-8 text-xs',
    md: 'h-10 w-10 text-sm',
    lg: 'h-14 w-14 text-base',
  }[size] || 'h-10 w-10 text-sm'

  if (src) {
    return <img src={resolveMediaUrl(src)} alt={alt || name || 'avatar'} className={`${sizeClass} rounded-xl border border-brand-line object-cover`} />
  }

  return (
    <div className={`${sizeClass} flex items-center justify-center rounded-xl border border-brand-line bg-brand-red/20 font-semibold text-brand-white`}>
      {initials}
    </div>
  )
}
