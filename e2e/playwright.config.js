import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'

dotenv.config()

// Puerto del Vite local. Los proyectos por org usan subdominios *.localhost
// (Chromium los resuelve a 127.0.0.1). Los specs de API conectan a 127.0.0.1:8000
// y mandan X-Forwarded-Host (ver tests/multiorg/_helpers.js).
const PORT = process.env.QA_WEB_PORT || '5173'
const sub = (s) => `http://${s}.localhost:${PORT}`

export default defineConfig({
  testDir: './tests/multiorg',
  globalSetup: './global-setup.multiorg.js',

  // Estado compartido en la BD (creación de usuarios/orgs) → SERIAL.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // 1 reintento local para absorber flakes transitorios de infra (p.ej. un connect
  // ETIMEDOUT puntual al runserver compartiendo puerto con el proxy de Docker).
  retries: process.env.CI ? 2 : 1,

  timeout: 60_000,
  expect: { timeout: 15_000 },

  reporter: [
    ['list'],
    ['html', { outputFolder: 'reportes', open: 'never' }],
  ],

  use: {
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    ignoreHTTPSErrors: true,
    locale: 'es-CL',
    timezoneId: 'America/Santiago',
  },

  projects: [
    // superadmin (apex): specs de API (10-16) + UI de superadmin (20).
    {
      name: 'superadmin',
      testMatch: /(1[0-6]|20)-.*\.spec\.js$/,
      use: { ...devices['Desktop Chrome'], baseURL: `http://localhost:${PORT}` },
    },
    // gym-test (subdominio): UI del email compartido como profesor (30).
    {
      name: 'gym-test',
      testMatch: /30-.*\.spec\.js$/,
      use: { ...devices['Desktop Chrome'], baseURL: sub('gym-test') },
    },
    // e2e-gym (subdominio): UI del gym_admin de esa org (40).
    {
      name: 'e2e-gym',
      testMatch: /40-.*\.spec\.js$/,
      use: { ...devices['Desktop Chrome'], baseURL: sub('e2e-gym') },
    },
  ],
})
