import sharp from 'sharp'
import { fileURLToPath } from 'node:url'

const publicPath = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))

const source = publicPath('icono.png')
const BRAND_BACKGROUND = '#09090b'
const MASKABLE_ARTWORK_SIZE = 376

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

async function writePwaIcon(size, out) {
  await sharp(await getApprovedArtwork())
    .resize(size, size, { fit: 'contain', withoutEnlargement: false })
    .png({ compressionLevel: 9 })
    .toFile(publicPath(out))
  console.log(`wrote ${out} (${size}x${size}, approved transparency)`)
}

async function writeMaskableIcon() {
  // A maskable icon is layered differently from the regular icon: the brand
  // background is full bleed and opaque, while the approved artwork is scaled
  // uniformly so the T remains inside Android's guaranteed safe-zone circle.
  const icon = await sharp(await getApprovedArtwork())
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
      background: BRAND_BACKGROUND,
    },
  })
    .composite([{ input: icon, gravity: 'center' }])
    .png({ compressionLevel: 9 })
    .toFile(publicPath('pwa-maskable-512x512-v2.png'))

  console.log('wrote pwa-maskable-512x512-v2.png (512x512, opaque maskable safe-zone)')
}

async function writeAppleTouchIcon() {
  await sharp(await getApprovedArtwork())
    .resize(180, 180, { fit: 'contain', withoutEnlargement: false })
    .flatten({ background: BRAND_BACKGROUND })
    .png({ compressionLevel: 9 })
    .toFile(publicPath('apple-touch-icon-v2.png'))

  console.log('wrote apple-touch-icon-v2.png (180x180, opaque)')
}

await writePwaIcon(192, 'pwa-192x192-v2.png')
await writePwaIcon(512, 'pwa-512x512-v2.png')
await writeMaskableIcon()
await writeAppleTouchIcon()

console.log('Iconos oficiales TYMRO regenerados.')
