import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'

const rootPath = (name) => fileURLToPath(new URL(`../${name}`, import.meta.url))
const publicPath = (name) => rootPath(`public/${name}`)
const distPath = (name) => rootPath(`dist/${name}`)

const icons = [
  { file: 'pwa-192x192-v3.png', width: 192, height: 192, purpose: 'any' },
  { file: 'pwa-512x512-v3.png', width: 512, height: 512, purpose: 'any' },
  { file: 'pwa-maskable-512x512-v3.png', width: 512, height: 512, purpose: 'maskable' },
]
const appleIcon = 'apple-touch-icon-v3.png'
const oldManifestAssets = [
  'pwa-192x192.png',
  'pwa-192x192-v2.png',
  'pwa-512x512.png',
  'pwa-512x512-v2.png',
  'pwa-maskable-512x512.png',
  'pwa-maskable-512x512-v2.png',
  'apple-touch-icon.png',
  'apple-touch-icon-v2.png',
]

async function pngStats(file) {
  const metadata = await sharp(file, { limitInputPixels: false }).metadata()
  const { data: pixels, info } = await sharp(file, { limitInputPixels: false })
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  let minX = info.width
  let minY = info.height
  let maxX = -1
  let maxY = -1
  let minAlpha = 255
  let opaquePixels = 0
  let whiteEdgePixels = 0

  for (let y = 0; y < info.height; y += 1) {
    for (let x = 0; x < info.width; x += 1) {
      const offset = (y * info.width + x) * 4
      const red = pixels[offset]
      const green = pixels[offset + 1]
      const blue = pixels[offset + 2]
      const alpha = pixels[offset + 3]
      minAlpha = Math.min(minAlpha, alpha)
      if (alpha === 255) opaquePixels += 1
      if (alpha > 0) {
        minX = Math.min(minX, x)
        minY = Math.min(minY, y)
        maxX = Math.max(maxX, x)
        maxY = Math.max(maxY, y)
      }
      if (
        (x === 0 || y === 0 || x === info.width - 1 || y === info.height - 1)
        && red > 245 && green > 245 && blue > 245
      ) {
        whiteEdgePixels += 1
      }
    }
  }

  const corners = [
    Array.from(pixels.slice(0, 4)),
    Array.from(pixels.slice((info.width - 1) * 4, (info.width - 1) * 4 + 4)),
    Array.from(pixels.slice((info.height - 1) * info.width * 4, (info.height - 1) * info.width * 4 + 4)),
    Array.from(pixels.slice((info.width * info.height - 1) * 4, (info.width * info.height - 1) * 4 + 4)),
  ]

  return {
    width: info.width,
    height: info.height,
    hasAlpha: metadata.hasAlpha === true,
    bbox: [minX, minY, maxX, maxY],
    minAlpha,
    fullyOpaque: opaquePixels === info.width * info.height,
    whiteEdgePixels,
    corners,
  }
}

const manifestRaw = readFileSync(distPath('manifest.webmanifest'), 'utf8')
const manifest = JSON.parse(manifestRaw)
const indexHtml = readFileSync(distPath('index.html'), 'utf8')
const serviceWorker = readFileSync(distPath('sw.js'), 'utf8')

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
  assert.equal(serviceWorker.includes(asset), true, `${asset} no esta en el SW`)
}

for (const oldAsset of oldManifestAssets) {
  assert.equal(manifestRaw.includes(oldAsset), false, `El manifest todavia referencia ${oldAsset}`)
}

const installableStats = {}
for (const { file, width, height } of icons) {
  const stats = await pngStats(publicPath(file))
  installableStats[file] = stats
  assert.deepEqual([stats.width, stats.height], [width, height])
  assert.equal(stats.minAlpha, 255, `${file} tiene alpha menor a 255`)
  assert.equal(stats.fullyOpaque, true, `${file} debe ser completamente opaco`)
  assert.equal(stats.whiteEdgePixels, 0, `${file} tiene pixeles blancos en el borde`)
  assert.deepEqual(stats.bbox, [0, 0, width - 1, height - 1], `${file} no ocupa el canvas completo`)
  assert.deepEqual(stats.corners.map((corner) => corner[3]), [255, 255, 255, 255])
}

const appleStats = await pngStats(publicPath(appleIcon))
installableStats[appleIcon] = appleStats
assert.deepEqual([appleStats.width, appleStats.height], [180, 180])
assert.equal(appleStats.minAlpha, 255)
assert.equal(appleStats.fullyOpaque, true)
assert.equal(appleStats.whiteEdgePixels, 0)
assert.deepEqual(appleStats.bbox, [0, 0, 179, 179])
assert.deepEqual(appleStats.corners.map((corner) => corner[3]), [255, 255, 255, 255])
assert.equal(indexHtml.includes(`/${appleIcon}`), true)
assert.equal(indexHtml.includes('/apple-touch-icon-v2.png'), false)
assert.equal(indexHtml.includes('apple-touch-startup-image'), false)
assert.equal(indexHtml.includes('/pwa-512x512-v3.png'), true)
assert.equal(indexHtml.includes('/pwa-192x192-v2.png'), false)

console.log(JSON.stringify({
  icons: Object.fromEntries(Object.entries(installableStats).map(([file, stats]) => [file, {
    dimensions: `${stats.width}x${stats.height}`,
    hasAlpha: stats.hasAlpha,
    minAlpha: stats.minAlpha,
    corners: stats.corners,
    whiteEdgePixels: stats.whiteEdgePixels,
    bbox: stats.bbox,
  }])),
  manifestIcons: manifest.icons.map((icon) => icon.src),
  appleTouchIcon: `/${appleIcon}`,
}, null, 2))
