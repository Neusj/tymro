// Generates the iOS apple-touch-startup-image assets from the approved TYMRO
// icon. iOS shows these before the HTML splash in #root can render.
//
// Portrait only: the app manifest is orientation: portrait. The native pixel
// matrix is declared in index.html next to each apple-touch-startup-image link.
// Run: npm run splash
//
// Android does not use these files; its splash is derived from the manifest.
import sharp from 'sharp'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BG = '#09090b'
const ACCENT = '#f97316'
const ICON_FRACTION = 0.38

const publicPath = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))
const sourceIcon = publicPath('icono.png')

// widthPx x heightPx = native portrait framebuffer size.
const targets = [
  { file: 'iphone-1320x2868.png', w: 1320, h: 2868 }, // 16 Pro Max
  { file: 'iphone-1206x2622.png', w: 1206, h: 2622 }, // 16 Pro
  { file: 'iphone-1290x2796.png', w: 1290, h: 2796 }, // 16 Plus / 15 Pro Max / 15 Plus / 14 Pro Max
  { file: 'iphone-1179x2556.png', w: 1179, h: 2556 }, // 16 / 15 Pro / 15 / 14 Pro
  { file: 'iphone-1284x2778.png', w: 1284, h: 2778 }, // 14 Plus / 13 Pro Max / 12 Pro Max
  { file: 'iphone-1170x2532.png', w: 1170, h: 2532 }, // 14 / 13 Pro / 13 / 12 Pro / 12
  { file: 'iphone-1242x2688.png', w: 1242, h: 2688 }, // 11 Pro Max / XS Max
  { file: 'iphone-828x1792.png', w: 828, h: 1792 }, // 11 / XR
  { file: 'iphone-1125x2436.png', w: 1125, h: 2436 }, // 11 Pro / XS / X / 13 mini / 12 mini
  { file: 'iphone-1242x2208.png', w: 1242, h: 2208 }, // 8 Plus / 7 Plus / 6s Plus
  { file: 'iphone-750x1334.png', w: 750, h: 1334 }, // SE 2/3 / 8 / 7 / 6s
  { file: 'iphone-640x1136.png', w: 640, h: 1136 }, // SE 1 / 5s / 5
]

const outDir = fileURLToPath(new URL('../public/splash/', import.meta.url))
mkdirSync(outDir, { recursive: true })

function backgroundSvg(width, height) {
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <radialGradient id="gO" cx="${Math.round(width * 0.12)}" cy="${Math.round(-height * 0.02)}" r="${Math.round(height * 0.55)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="${ACCENT}" stop-opacity=".10"/><stop offset=".5" stop-color="${ACCENT}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="gB" cx="${width}" cy="0" r="${Math.round(height * 0.5)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2563eb" stop-opacity=".10"/><stop offset=".45" stop-color="#2563eb" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="${width}" height="${height}" fill="${BG}"/>
  <rect width="${width}" height="${height}" fill="url(#gO)"/>
  <rect width="${width}" height="${height}" fill="url(#gB)"/>
</svg>`)
}

for (const { file, w, h } of targets) {
  const iconSize = Math.round(Math.min(w, h) * ICON_FRACTION)
  const icon = await sharp(sourceIcon)
    .resize(iconSize, iconSize, { fit: 'contain', withoutEnlargement: false })
    .png()
    .toBuffer()

  await sharp(backgroundSvg(w, h))
    .composite([{ input: icon, gravity: 'center' }])
    .png({ compressionLevel: 9 })
    .toFile(outDir + file)

  console.log(`wrote splash/${file} (${w}x${h})`)
}

console.log(`Splash iOS regenerados (${targets.length}).`)
