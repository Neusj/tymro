import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'

dotenv.config()

const baseURL = process.env.QA_BASE_URL || 'https://qa.tymroapp.com'

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.js',

  // Estado compartido (saldo del mismo alumno) → SERIAL obligatorio.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,

  timeout: 60_000,
  expect: { timeout: 15_000 },

  reporter: [
    ['list'],
    ['html', { outputFolder: 'reportes', open: 'never' }],
  ],

  use: {
    baseURL,
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
    // Setups de alumno (00) y profesor (00b): login válido UNA vez y guardan sesión.
    // (El backend ROTA el token en cada login, así que cada rol se loguea una vez.)
    { name: 'setup', testMatch: /(00-auth|00b-teacher-auth)\.setup\.js/ },
    {
      name: 'chromium',
      testIgnore: [/auth\.setup\.js/, /gym-admin/],
      use: { ...devices['Desktop Chrome'], storageState: 'storageState.student.json' },
      dependencies: ['setup'],
    },

    // Suite gym_admin (org e2e-gym): aislada, su propio setup y storageState.
    // Correr con:  npx playwright test --project=gym-admin
    { name: 'setup-gym', testMatch: /20-gym-admin-auth\.setup\.js/ },
    {
      name: 'gym-admin',
      testMatch: /gym-admin.*\.spec\.js/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'storageState.gym.json',
        screenshot: 'on', // capturar pantalla de cada flujo para el reporte
      },
      dependencies: ['setup-gym'],
    },
  ],
})
