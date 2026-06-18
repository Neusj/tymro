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
// La "T" ya cae dentro de la zona segura del 80%, así que sirve tanto para la
// maskable (Android le aplica su máscara) como para apple-touch (iOS la redondea).
const square = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="${BG}"/>
  <rect x="225" y="123" width="62" height="266" rx="11" fill="${STEM}"/>
  <rect x="123" y="123" width="266" height="59" rx="17" fill="${ACCENT}"/>
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
