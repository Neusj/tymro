// Opciones de vite-plugin-pwa extraídas de vite.config.js para poder testear el
// contrato de actualización PWA (ver pwaOptions.test.js). El comportamiento es idéntico:
// vite.config.js hace `VitePWA(pwaOptions)`.
export const pwaOptions = {
  // Permite desactivar el service worker (p.ej. en E2E, donde el SW puede
  // servir un shell cacheado y enmascarar cambios). VITE_DISABLE_PWA=1.
  disable: process.env.VITE_DISABLE_PWA === '1',
  // 'prompt' conserva el aviso visible de actualizacion. El SW nuevo toma control
  // al instalarse; el boton aplica una recarga fuerte si el navegador queda pegado.
  registerType: 'prompt',
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
    // Los splash de iOS (apple-touch-startup-image) NO van al precache: son ~1 MB
    // de cosméticos que iOS pide por HTTP al lanzar (no los sirve el SW al shell),
    // así el precache no se infla ni los re-valida en cada update. Siguen en dist/.
    globIgnores: ['splash/**'],
    // SPA: cualquier navegación offline cae al app-shell (index.html).
    navigateFallback: '/index.html',
    // No interceptar las rutas de la API ni media con el fallback de navegación.
    navigateFallbackDenylist: [/^\/api\//, /^\/media\//],
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: true,
    importScripts: ['push-sw.js'],
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
}
