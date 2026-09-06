import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'

const rootPath = (name) => fileURLToPath(new URL(`../${name}`, import.meta.url))
const publicPath = (name) => rootPath(`public/${name}`)
const distPath = (name) => rootPath(`dist/${name}`)

const icons = [
  { file: 'pwa-192x192-v2.png', width: 192, height: 192, purpose: 'any' },
  { file: 'pwa-512x512-v2.png', width: 512, height: 512, purpose: 'any' },
  { file: 'pwa-maskable-512x512-v2.png', width: 512, height: 512, purpose: 'maskable' },
]
const appleIcon = 'apple-touch-icon-v2.png'
const splashes = [
  ['iphone-1320x2868-v2.png', 1320, 2868],
  ['iphone-1206x2622-v2.png', 1206, 2622],
  ['iphone-1290x2796-v2.png', 1290, 2796],
  ['iphone-1179x2556-v2.png', 1179, 2556],
  ['iphone-1284x2778-v2.png', 1284, 2778],
  ['iphone-1170x2532-v2.png', 1170, 2532],
  ['iphone-1242x2688-v2.png', 1242, 2688],
  ['iphone-828x1792-v2.png', 828, 1792],
  ['iphone-1125x2436-v2.png', 1125, 2436],
  ['iphone-1242x2208-v2.png', 1242, 2208],
  ['iphone-750x1334-v2.png', 750, 1334],
  ['iphone-640x1136-v2.png', 640, 1136],
]
const oldAssets = [
  'pwa-192x192.png',
  'pwa-512x512.png',
  'pwa-maskable-512x512.png',
  'apple-touch-icon.png',
]

async function pngStats(file) {
  const image = sharp(file, { limitInputPixels: false }).ensureAlpha()
  const metadata = await image.metadata()
  const pixels = await image.raw().toBuffer()
  let minX = metadata.width
  let minY = metadata.height
  let maxX = -1
  let maxY = -1
  let opaquePixels = 0
  let whiteEdgePixels = 0

  for (let y = 0; y < metadata.height; y += 1) {
    for (let x = 0; x < metadata.width; x += 1) {
      const offset = (y * metadata.width + x) * 4
      const red = pixels[offset]
      const green = pixels[offset + 1]
      const blue = pixels[offset + 2]
      const alpha = pixels[offset + 3]
      if (alpha === 255) opaquePixels += 1
      if (alpha > 3) {
        minX = Math.min(minX, x)
        minY = Math.min(minY, y)
        maxX = Math.max(maxX, x)
        maxY = Math.max(maxY, y)
      }
      if (
        (x === 0 || y === 0 || x === metadata.width - 1 || y === metadata.height - 1)
        && alpha > 0 && red > 245 && green > 245 && blue > 245
      ) {
        whiteEdgePixels += 1
      }
    }
  }

  const cornerAlpha = [
    pixels[3],
    pixels[(metadata.width - 1) * 4 + 3],
    pixels[((metadata.height - 1) * metadata.width) * 4 + 3],
    pixels[(metadata.width * metadata.height - 1) * 4 + 3],
  ]

  return {
    width: metadata.width,
    height: metadata.height,
    bbox: [minX, minY, maxX, maxY],
    fullyOpaque: opaquePixels === metadata.width * metadata.height,
    whiteEdgePixels,
    cornerAlpha,
  }
}

const manifestRaw = readFileSync(distPath('manifest.webmanifest'), 'utf8')
const manifest = JSON.parse(manifestRaw)
const indexHtml = readFileSync(distPath('index.html'), 'utf8')
const serviceWorker = readFileSync(distPath('sw.js'), 'utf8')
const pushWorker = readFileSync(distPath('push-sw.js'), 'utf8')
const builtSurfaces = [manifestRaw, indexHtml, serviceWorker, pushWorker]

assert.equal(manifest.start_url, '/')
assert.equal(manifest.scope, '/')
assert.equal(manifest.display, 'standalone')
assert.equal(Object.hasOwn(manifest, 'id'), false)
assert.deepEqual(
  manifest.icons,
  icons.map(({ file, width, height, purpose }) => ({
    src: file,
    sizes: `${width}x${height}`,
    type: 'image/png',
    purpose,
  })),
)

for (const asset of [...icons.map(({ file }) => file), appleIcon]) {
  assert.equal(existsSync(publicPath(asset)), true, `Falta public/${asset}`)
  assert.equal(existsSync(distPath(asset)), true, `Falta dist/${asset}`)
  assert.equal(serviceWorker.includes(asset), true, `${asset} no está en el SW`)
}
for (const oldAsset of oldAssets) {
  assert.equal(
    builtSurfaces.some((surface) => surface.includes(`/${oldAsset}`) || surface.includes(`\"${oldAsset}\"`)),
    false,
    `El build todavía referencia ${oldAsset}`,
  )
}

for (const { file, width, height, purpose } of icons) {
  const stats = await pngStats(publicPath(file))
  assert.deepEqual([stats.width, stats.height], [width, height])
  assert.equal(stats.whiteEdgePixels, 0, `${file} tiene píxeles blancos en el borde`)
  if (purpose === 'maskable') {
    assert.equal(stats.fullyOpaque, true, `${file} debe ser completamente opaco`)
    assert.deepEqual(stats.cornerAlpha, [255, 255, 255, 255])
  } else {
    assert.equal(stats.bbox[0], 0, `${file} conserva margen izquierdo`)
    assert.equal(stats.bbox[2], width - 1, `${file} conserva margen derecho`)
    assert.equal(stats.bbox[1] <= 8, true, `${file} conserva demasiado margen superior`)
    assert.equal(stats.bbox[3] >= height - 8, true, `${file} conserva demasiado margen inferior`)
  }
}

const appleStats = await pngStats(publicPath(appleIcon))
assert.deepEqual([appleStats.width, appleStats.height], [180, 180])
assert.equal(appleStats.fullyOpaque, true)
assert.equal(appleStats.whiteEdgePixels, 0)
assert.deepEqual(appleStats.cornerAlpha, [255, 255, 255, 255])
assert.equal(indexHtml.includes(`/${appleIcon}`), true)

for (const [file, width, height] of splashes) {
  assert.equal(existsSync(publicPath(`splash/${file}`)), true, `Falta public/splash/${file}`)
  assert.equal(existsSync(distPath(`splash/${file}`)), true, `Falta dist/splash/${file}`)
  assert.equal(indexHtml.includes(`/splash/${file}`), true, `${file} no está en index.html`)
  const stats = await pngStats(publicPath(`splash/${file}`))
  assert.deepEqual([stats.width, stats.height], [width, height])
  assert.equal(stats.fullyOpaque, true, `${file} debe ser completamente opaco`)
  assert.equal(stats.whiteEdgePixels, 0, `${file} tiene píxeles blancos en el borde`)
}

console.log('PWA assets OK: 4 iconos, 12 splash, manifest, referencias y precache.')
