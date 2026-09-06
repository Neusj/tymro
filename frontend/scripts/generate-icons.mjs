import sharp from 'sharp'
import { fileURLToPath } from 'node:url'

const publicPath = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))

const source = publicPath('icono.png')
const MASKABLE_ARTWORK_SIZE = 376
const V3_FILES = {
  pwa192: 'pwa-192x192-v3.png',
  pwa512: 'pwa-512x512-v3.png',
  maskable: 'pwa-maskable-512x512-v3.png',
  apple: 'apple-touch-icon-v3.png',
}

async function cleanTransparentEdges(input, alphaThreshold = 3) {
  const image = sharp(input, { limitInputPixels: false }).ensureAlpha()
  const metadata = await image.metadata()
  const pixels = await image.raw().toBuffer()

  for (let index = 3; index < pixels.length; index += 4) {
    if (pixels[index] <= alphaThreshold) {
      pixels[index] = 0
    }
  }

  return sharp(pixels, {
    raw: {
      width: metadata.width,
      height: metadata.height,
      channels: 4,
    },
  })
    .png()
    .toBuffer()
}

async function getApprovedArtwork() {
  const trimmed = await sharp(await cleanTransparentEdges(source))
    .trim({ background: { r: 0, g: 0, b: 0, alpha: 0 }, threshold: 1 })
    .png()
    .toBuffer()
  const { width, height } = await sharp(trimmed).metadata()
  const size = Math.max(width, height)
  const horizontal = size - width
  const vertical = size - height

  return sharp(trimmed)
    .extend({
      left: Math.floor(horizontal / 2),
      right: Math.ceil(horizontal / 2),
      top: Math.floor(vertical / 2),
      bottom: Math.ceil(vertical / 2),
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    })
    .png()
    .toBuffer()
}

async function makeFullBleedOpaque(input, size) {
  const background = await makeFullBleedBackground(input, size)
  const foreground = await sharp(input, { limitInputPixels: false })
    .resize(size, size, { fit: 'fill', withoutEnlargement: false })
    .ensureAlpha()
    .png()
    .toBuffer()

  return sharp(background)
    .composite([{ input: foreground, gravity: 'center' }])
    .removeAlpha()
    .png({ compressionLevel: 9 })
    .toBuffer()
}

async function makeFullBleedBackground(input, size) {
  const svg = `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="base" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#09090b"/>
          <stop offset="0.42" stop-color="#09090b"/>
          <stop offset="0.72" stop-color="#071325"/>
          <stop offset="1" stop-color="#002d7a"/>
        </linearGradient>
      </defs>
      <rect width="${size}" height="${size}" fill="url(#base)"/>
    </svg>
  `

  return sharp(Buffer.from(svg))
    .png({ compressionLevel: 9 })
    .toBuffer()
}

async function makeMarkLayer(input, canvasSize, markSize = canvasSize) {
  const { data: pixels, info } = await sharp(input, { limitInputPixels: false })
    .resize(markSize, markSize, { fit: 'fill', withoutEnlargement: false })
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  const { width, height } = info
  const candidates = new Uint8Array(width * height)
  const visited = new Uint8Array(width * height)

  for (let index = 0; index < candidates.length; index += 1) {
    const offset = index * 4
    const red = pixels[offset]
    const green = pixels[offset + 1]
    const blue = pixels[offset + 2]
    const alpha = pixels[offset + 3]
    const x = index % width
    const y = Math.floor(index / width)
    const warmMark = red > 105 && red > blue * 0.75 && green > 18
    const blueMark = blue > 130 && green > 70 && red < 95 && y < height * 0.48
    const awayFromContainerEdge = (
      x > width * 0.03
      && y > height * 0.03
      && x < width * 0.94
      && y < height * 0.94
    )

    if (alpha > 12 && awayFromContainerEdge && (warmMark || blueMark)) {
      candidates[index] = 1
    }
  }

  let bestComponent = []
  const queue = []
  for (let start = 0; start < candidates.length; start += 1) {
    if (!candidates[start] || visited[start]) continue

    const component = []
    let touchesEdge = false
    let minX = width
    let minY = height
    let maxX = -1
    let maxY = -1
    visited[start] = 1
    queue.length = 0
    queue.push(start)

    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const index = queue[cursor]
      const x = index % width
      const y = Math.floor(index / width)
      component.push(index)
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
      if (x <= 1 || y <= 1 || x >= width - 2 || y >= height - 2) {
        touchesEdge = true
      }

      const neighbors = [
        x > 0 ? index - 1 : -1,
        x < width - 1 ? index + 1 : -1,
        y > 0 ? index - width : -1,
        y < height - 1 ? index + width : -1,
      ]
      for (const neighbor of neighbors) {
        if (neighbor >= 0 && candidates[neighbor] && !visited[neighbor]) {
          visited[neighbor] = 1
          queue.push(neighbor)
        }
      }
    }

    const componentWidth = maxX - minX + 1
    const componentHeight = maxY - minY + 1
    const isContainerGlow = componentWidth > width * 0.88 || componentHeight > height * 0.88
    if (!touchesEdge && !isContainerGlow && component.length > bestComponent.length) {
      bestComponent = component
    }
  }

  const markPixels = Buffer.alloc(width * height * 4)
  for (const index of bestComponent) {
    const offset = index * 4
    markPixels[offset] = pixels[offset]
    markPixels[offset + 1] = pixels[offset + 1]
    markPixels[offset + 2] = pixels[offset + 2]
    markPixels[offset + 3] = pixels[offset + 3]
  }

  const mark = await sharp(markPixels, {
    raw: {
      width,
      height,
      channels: 4,
    },
  })
    .png()
    .toBuffer()

  return sharp({
    create: {
      width: canvasSize,
      height: canvasSize,
      channels: 4,
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    },
  })
    .composite([{ input: mark, gravity: 'center' }])
    .png()
    .toBuffer()
}

async function writePwaIcon(size, out) {
  const artwork = await getApprovedArtwork()
  const background = await makeFullBleedBackground(artwork, size)
  const mark = await makeMarkLayer(artwork, size)

  await sharp(background)
    .composite([{ input: mark, gravity: 'center' }])
    .removeAlpha()
    .png({ compressionLevel: 9 })
    .toFile(publicPath(out))
  console.log(`wrote ${out} (${size}x${size}, full bleed opaque)`)
}

async function writeMaskableIcon() {
  const artwork = await getApprovedArtwork()
  const background = await makeFullBleedBackground(artwork, 512)
  const icon = await makeMarkLayer(artwork, 512, MASKABLE_ARTWORK_SIZE)

  await sharp(background)
    .composite([{ input: icon, gravity: 'center' }])
    .removeAlpha()
    .png({ compressionLevel: 9 })
    .toFile(publicPath(V3_FILES.maskable))

  console.log(`wrote ${V3_FILES.maskable} (512x512, full bleed opaque maskable safe-zone)`)
}

async function writeAppleTouchIcon() {
  await sharp(await makeFullBleedOpaque(await getApprovedArtwork(), 180))
    .toFile(publicPath(V3_FILES.apple))

  console.log(`wrote ${V3_FILES.apple} (180x180, full bleed opaque)`)
}

await writePwaIcon(192, V3_FILES.pwa192)
await writePwaIcon(512, V3_FILES.pwa512)
await writeMaskableIcon()
await writeAppleTouchIcon()

console.log('Iconos oficiales TYMRO v3 regenerados.')
