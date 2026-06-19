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
    // El setup hace el login válido del alumno UNA sola vez y guarda la sesión.
    // (El backend ROTA el token en cada login, así que el alumno se loguea una vez.)
    { name: 'setup', testMatch: /auth\.setup\.js/ },
    {
      name: 'chromium',
      testIgnore: /auth\.setup\.js/,
      use: { ...devices['Desktop Chrome'], storageState: 'storageState.student.json' },
      dependencies: ['setup'],
    },
  ],
})
