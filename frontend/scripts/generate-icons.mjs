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
  const { data: pixels, info } = await sharp(input, { limitInputPixels: false })
    .resize(size, size, { fit: 'fill', withoutEnlargement: false })
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  const { width, height } = info
  const nearest = new Int32Array(width * height)
  const distance = new Float64Array(width * height)
  const maxDistance = width * width + height * height

  for (let index = 0; index < nearest.length; index += 1) {
    const alpha = pixels[index * 4 + 3]
    nearest[index] = alpha === 255 ? index : -1
    distance[index] = alpha === 255 ? 0 : maxDistance
  }

  // Felzenszwalb/Huttenlocher distance transform in two dimensions, tracking
  // the source pixel so transparent rounded corners inherit the icon background.
  for (let y = 0; y < height; y += 1) {
    for (let x = 1; x < width; x += 1) {
      const index = y * width + x
      const previous = index - 1
      if (distance[previous] + 1 < distance[index]) {
        distance[index] = distance[previous] + 1
        nearest[index] = nearest[previous]
      }
    }
    for (let x = width - 2; x >= 0; x -= 1) {
      const index = y * width + x
      const next = index + 1
      if (distance[next] + 1 < distance[index]) {
        distance[index] = distance[next] + 1
        nearest[index] = nearest[next]
      }
    }
  }

  for (let x = 0; x < width; x += 1) {
    for (let y = 1; y < height; y += 1) {
      const index = y * width + x
      const previous = index - width
      if (distance[previous] + 1 < distance[index]) {
        distance[index] = distance[previous] + 1
        nearest[index] = nearest[previous]
      }
    }
    for (let y = height - 2; y >= 0; y -= 1) {
      const index = y * width + x
      const next = index + width
      if (distance[next] + 1 < distance[index]) {
        distance[index] = distance[next] + 1
        nearest[index] = nearest[next]
      }
    }
  }

  for (let index = 0; index < nearest.length; index += 1) {
    const sourceIndex = nearest[index]
    const targetOffset = index * 4
    const sourceOffset = sourceIndex * 4
    if (sourceIndex !== index) {
      pixels[targetOffset] = pixels[sourceOffset]
      pixels[targetOffset + 1] = pixels[sourceOffset + 1]
      pixels[targetOffset + 2] = pixels[sourceOffset + 2]
    }
    pixels[targetOffset + 3] = 255
  }

  return sharp(pixels, {
    raw: {
      width,
      height,
      channels: 4,
    },
  })
    .removeAlpha()
    .png({ compressionLevel: 9 })
    .toBuffer()
}

async function writePwaIcon(size, out) {
  await sharp(await makeFullBleedOpaque(await getApprovedArtwork(), size))
    .toFile(publicPath(out))
  console.log(`wrote ${out} (${size}x${size}, full bleed opaque)`)
}

async function writeMaskableIcon() {
  const icon = await sharp(await makeFullBleedOpaque(await getApprovedArtwork(), 512))
    .resize(MASKABLE_ARTWORK_SIZE, MASKABLE_ARTWORK_SIZE, {
      fit: 'contain',
      withoutEnlargement: false,
    })
    .png()
    .toBuffer()

  await sharp({
    create: {
      width: 512,
      height: 512,
      channels: 4,
      background: { r: 9, g: 9, b: 11, alpha: 1 },
    },
  })
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
