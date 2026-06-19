import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // Permite desactivar el service worker (p.ej. en E2E, donde el SW puede
      // servir un shell cacheado y enmascarar cambios). VITE_DISABLE_PWA=1.
      disable: process.env.VITE_DISABLE_PWA === '1',
      // 'autoUpdate' = cuando hay una nueva versión, el SW la instala y la
      // página se recarga automáticamente para tomarla (update policy).
      registerType: 'autoUpdate',
      // Activos sueltos de public/ que también queremos precachear/exponer.
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'TYMRO — Gestión de Gimnasios',
        short_name: 'TYMRO',
        description: 'Gestión de gimnasios: clases, reservas, asistencia y planes.',
        lang: 'es',
        dir: 'ltr',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#09090b',
        theme_color: '#09090b',
        categories: ['health', 'fitness', 'sports'],
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'pwa-maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Precache del shell estático (JS/CSS/HTML/fuentes/imágenes con hash).
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webp,woff,woff2}'],
        // SPA: cualquier navegación offline cae al app-shell (index.html).
        navigateFallback: '/index.html',
        // No interceptar las rutas de la API ni media con el fallback de navegación.
        navigateFallbackDenylist: [/^\/api\//, /^\/media\//],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        runtimeCaching: [
          {
            // API: NetworkFirst → online usa la red; offline muestra lo último
            // cacheado (clases, usuario, etc.). Solo GET (Workbox ignora POST,
            // así que login/escritura nunca se cachean).
            urlPattern: ({ url, request }) =>
              url.pathname.startsWith('/api/') && request.method === 'GET',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'tymro-api',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 120, maxAgeSeconds: 60 * 60 * 24 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // Imágenes subidas (logos, avatares): CacheFirst con expiración.
            urlPattern: ({ url }) => url.pathname.startsWith('/media/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'tymro-media',
              expiration: { maxEntries: 80, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      // Permite probar el PWA en `npm run dev`. En desarrollo el SW puede servir
      // assets cacheados: usa "Update on reload" en DevTools si ves algo viejo.
      devOptions: {
        enabled: true,
        type: 'module',
        navigateFallback: 'index.html',
      },
    }),
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: [
      '.trycloudflare.com',
      'tymroapp.com',
      '.tymroapp.com',  // subdominios de tenant en prod
      '.localhost',     // subdominios de tenant en dev (r2b-qa.localhost, gym-test.localhost, ...)
      'localhost',
      '127.0.0.1',
    ],
    proxy: {
      // changeOrigin:false + xfwd:true ⇒ el backend recibe el Host del subdominio
      // (y X-Forwarded-Host), que OrganizationMiddleware usa para resolver la org.
      // Con changeOrigin:true el Host se reescribiría a 127.0.0.1 y se perdería el tenant.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        xfwd: true,
      },
      '/media': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        xfwd: true,
      },
    },
  },
})
