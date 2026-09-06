import sharp from 'sharp'
import { fileURLToPath } from 'node:url'

const publicPath = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))

const source = publicPath('icono.png')
const MASKABLE_SAFE_SIZE = 320 // Keeps the approved wide T inside Android's safe-zone circle.

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

async function writePwaIcon(size, out) {
  await sharp(source)
    .resize(size, size, { fit: 'contain', withoutEnlargement: false })
    .png({ compressionLevel: 9 })
    .toFile(publicPath(out))
  console.log(`wrote ${out} (${size}x${size}, transparent)`)
}

async function writeMaskableIcon() {
  const icon = await sharp(await cleanTransparentEdges(source))
    .trim({ background: { r: 0, g: 0, b: 0, alpha: 0 }, threshold: 1 })
    .resize(MASKABLE_SAFE_SIZE, MASKABLE_SAFE_SIZE, {
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
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    },
  })
    .composite([{ input: icon, gravity: 'center' }])
    .png({ compressionLevel: 9 })
    .toFile(publicPath('pwa-maskable-512x512.png'))

  console.log('wrote pwa-maskable-512x512.png (512x512, maskable safe-zone)')
}

async function writeAppleTouchIcon() {
  await sharp(await cleanTransparentEdges(source))
    .resize(180, 180, { fit: 'contain', withoutEnlargement: false })
    .png({ compressionLevel: 9 })
    .toFile(publicPath('apple-touch-icon.png'))

  console.log('wrote apple-touch-icon.png (180x180, transparent)')
}

await writePwaIcon(192, 'pwa-192x192.png')
await writePwaIcon(512, 'pwa-512x512.png')
await writeMaskableIcon()
await writeAppleTouchIcon()

console.log('Iconos oficiales TYMRO regenerados.')
