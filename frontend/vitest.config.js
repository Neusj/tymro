import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Config separada de vite.config.js a propósito: NO arrastra el plugin VitePWA
// (service worker / runtime caching) que no aplica a tests unitarios de UI y que
// puede interferir en jsdom. Vitest usa este archivo con preferencia sobre vite.config.js.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    include: ['src/**/*.{test,spec}.{js,jsx}'],
    // La app es de un gimnasio chileno y el backend responde fechas en America/Santiago.
    // Fijar la zona hace que los tests de fecha valgan en cualquier máquina: el bug de
    // interpretar 'YYYY-MM-DD' como UTC solo se manifiesta al oeste de Greenwich, así que
    // en un CI en UTC pasarían igual estando rotos.
    env: { TZ: 'America/Santiago' },
  },
})
