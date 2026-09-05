import sharp from 'sharp'
import { fileURLToPath } from 'node:url'

const publicPath = (name) => fileURLToPath(new URL(`../public/${name}`, import.meta.url))

const source = publicPath('icono.png')
const targets = [
  { size: 192, out: 'pwa-192x192.png' },
  { size: 512, out: 'pwa-512x512.png' },
  { size: 512, out: 'pwa-maskable-512x512.png' },
  { size: 180, out: 'apple-touch-icon.png' },
]

for (const { size, out } of targets) {
  await sharp(source).resize(size, size, { fit: 'cover' }).png().toFile(publicPath(out))
  console.log(`wrote ${out} (${size}x${size})`)
}

console.log('Iconos oficiales TYMRO regenerados.')
