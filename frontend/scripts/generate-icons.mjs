// Regenera los íconos PNG de la PWA desde el SVG de marca (public/favicon.svg).
// La "T" usa el acento naranja de la paleta (#f97316). Ejecutar: npm run icons
import sharp from 'sharp'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const ACCENT = '#f97316'
const STEM = '#fafafa'
const BG = '#09090b'

const publicPath = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))

// Ícono "any" / favicon: cuadrado redondeado con borde (mismo diseño de marca).
const base = readFileSync(publicPath('favicon.svg'))

// Variante cuadrada opaca a sangre completa (sin borde ni esquinas redondeadas).
// Mismo diseño que favicon.svg pero SIN borde (Android le aplica su máscara y iOS
// la redondea). Conserva los glows y la T degradada; la "T" cae dentro de la zona
// segura del 80%.
const square = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="tfill" x1="256" y1="126" x2="256" y2="392" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fdba74"/>
      <stop offset=".55" stop-color="${ACCENT}"/>
      <stop offset="1" stop-color="#ea580c"/>
    </linearGradient>
    <radialGradient id="gr" cx="78" cy="74" r="300" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#dc2626" stop-opacity=".30"/><stop offset="1" stop-color="#dc2626" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="gb" cx="446" cy="452" r="320" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2563eb" stop-opacity=".28"/><stop offset="1" stop-color="#2563eb" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="go" cx="92" cy="446" r="250" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="${ACCENT}" stop-opacity=".22"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="${BG}"/>
  <rect width="512" height="512" fill="url(#gr)"/>
  <rect width="512" height="512" fill="url(#gb)"/>
  <rect width="512" height="512" fill="url(#go)"/>
  <g fill="url(#tfill)">
    <rect x="112" y="132" width="288" height="56" rx="10"/>
    <rect x="228" y="132" width="56" height="252" rx="10"/>
  </g>
</svg>`)

const targets = [
  { src: base, size: 192, out: 'pwa-192x192.png' },
  { src: base, size: 512, out: 'pwa-512x512.png' },
  { src: square, size: 512, out: 'pwa-maskable-512x512.png' },
  { src: square, size: 180, out: 'apple-touch-icon.png' },
]

for (const { src, size, out } of targets) {
  await sharp(src, { density: 384 }).resize(size, size).png().toFile(publicPath(out))
  console.log(`✓ ${out} (${size}x${size})`)
}
console.log('Íconos regenerados.')
