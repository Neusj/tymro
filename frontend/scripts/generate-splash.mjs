// Genera las apple-touch-startup-image (splash de arranque en frío de iOS) desde
// el mismo diseño de marca del ícono PWA: fondo #09090b + glows suaves + la "T"
// naranja centrada. iOS las muestra al lanzar la PWA instalada ANTES de cargar el
// HTML, así que evitan la pantalla en blanco previa al splash HTML de #root.
//
// Solo PORTRAIT: la app es orientation:portrait (ver src/pwa/pwaOptions.js).
// La matriz (px nativos / dpr / media query) está en index.html junto a cada
// <link>. Ejecutar: npm run splash
//
// Android NO usa esto: su splash lo deriva el navegador del manifest (background_color
// + theme_color + íconos). No tocar esa ruta.
import sharp from 'sharp'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BG = '#09090b'
const ACCENT = '#f97316'

// widthPx x heightPx = tamaño nativo del framebuffer en portrait (matriz verificada
// para iPhones comunes/actuales; ver los <link media> en index.html).
const targets = [
  { file: 'iphone-1320x2868.png', w: 1320, h: 2868 }, // 16 Pro Max
  { file: 'iphone-1206x2622.png', w: 1206, h: 2622 }, // 16 Pro
  { file: 'iphone-1290x2796.png', w: 1290, h: 2796 }, // 16 Plus / 15 Pro Max / 15 Plus / 14 Pro Max
  { file: 'iphone-1179x2556.png', w: 1179, h: 2556 }, // 16 / 15 Pro / 15 / 14 Pro
  { file: 'iphone-1284x2778.png', w: 1284, h: 2778 }, // 14 Plus / 13 Pro Max / 12 Pro Max
  { file: 'iphone-1170x2532.png', w: 1170, h: 2532 }, // 14 / 13 Pro / 13 / 12 Pro / 12
  { file: 'iphone-1242x2688.png', w: 1242, h: 2688 }, // 11 Pro Max / XS Max
  { file: 'iphone-828x1792.png', w: 828, h: 1792 },   // 11 / XR
  { file: 'iphone-1125x2436.png', w: 1125, h: 2436 }, // 11 Pro / XS / X / 13 mini / 12 mini
  { file: 'iphone-1242x2208.png', w: 1242, h: 2208 }, // 8 Plus / 7 Plus / 6s Plus
  { file: 'iphone-750x1334.png', w: 750, h: 1334 },   // SE 2/3 / 8 / 7 / 6s
  { file: 'iphone-640x1136.png', w: 640, h: 1136 },   // SE 1 / 5s / 5
]

const outDir = fileURLToPath(new URL('../public/splash/', import.meta.url))
mkdirSync(outDir, { recursive: true })

function splashSvg(W, H) {
  // La "T" ocupa una caja cuadrada centrada = 60% del lado corto (portrait ⇒ W).
  const box = Math.round(Math.min(W, H) * 0.6)
  const s = box / 512
  const bx = Math.round((W - box) / 2)
  const by = Math.round((H - box) / 2)
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <radialGradient id="gO" cx="${Math.round(W * 0.12)}" cy="${Math.round(-H * 0.02)}" r="${Math.round(H * 0.55)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="${ACCENT}" stop-opacity=".10"/><stop offset=".5" stop-color="${ACCENT}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="gB" cx="${W}" cy="0" r="${Math.round(H * 0.5)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2563eb" stop-opacity=".10"/><stop offset=".45" stop-color="#2563eb" stop-opacity="0"/>
    </radialGradient>
    <!-- userSpaceOnUse: las coords 256,126→256,392 se resuelven en el espacio del
         <g> que referencia el gradiente (que ya lleva el translate+scale), así que
         quedan alineadas con la "T" sin gradientTransform extra. -->
    <linearGradient id="tfill" x1="256" y1="126" x2="256" y2="392" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fdba74"/><stop offset=".55" stop-color="${ACCENT}"/><stop offset="1" stop-color="#ea580c"/>
    </linearGradient>
  </defs>
  <rect width="${W}" height="${H}" fill="${BG}"/>
  <rect width="${W}" height="${H}" fill="url(#gO)"/>
  <rect width="${W}" height="${H}" fill="url(#gB)"/>
  <g transform="translate(${bx} ${by}) scale(${s})" fill="url(#tfill)">
    <rect x="112" y="132" width="288" height="56" rx="10"/>
    <rect x="228" y="132" width="56" height="252" rx="10"/>
  </g>
</svg>`)
}

for (const { file, w, h } of targets) {
  await sharp(splashSvg(w, h)).png().toFile(outDir + file)
  console.log(`✓ splash/${file} (${w}x${h})`)
}
console.log(`Splash iOS regenerados (${targets.length}).`)
