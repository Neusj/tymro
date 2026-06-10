import { useEffect, useState } from 'react'

/**
 * Devuelve true cuando la media query coincide y se actualiza al cambiar el viewport.
 * Mismo patrón de matchMedia usado en AppLayout.
 */
export default function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined') {
      return false
    }
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined
    }
    const mediaQuery = window.matchMedia(query)
    const handleChange = (event) => setMatches(event.matches)
    mediaQuery.addEventListener('change', handleChange)
    setMatches(mediaQuery.matches)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [query])

  return matches
}
