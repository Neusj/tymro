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
  },
})
