import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { pwaOptions } from './src/pwa/pwaOptions'

export default defineConfig({
  plugins: [
    react(),
    // Opciones en src/pwa/pwaOptions.js (importable/testeable). El contrato de
    // actualizacion PWA (prompt + skipWaiting + clientsClaim) esta cubierta por
    // src/pwa/pwaOptions.test.js.
    VitePWA(pwaOptions),
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
