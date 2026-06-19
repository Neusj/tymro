import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Seed automático antes de la suite multi-org: puebla r2b-qa + gym-test + e2e-gym
// (con subdominios y email compartido) vía el venv local del backend.
// Se omite con QA_SKIP_SEED=1 (p.ej. cuando ya se sembró manualmente).
// Espera a que el backend responda /api/health/ (warmup): evita un ETIMEDOUT
// transitorio en el primer request del primer test contra runserver recién idle.
async function warmupBackend() {
  const url = (process.env.QA_BACKEND_URL || 'http://127.0.0.1:8000') + '/api/health/'
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(url)
      if (r.ok) {
        console.log('[multiorg] backend OK (/api/health/).')
        return
      }
    } catch {
      // backend aún no responde; reintenta
    }
    await new Promise((res) => setTimeout(res, 500))
  }
  console.warn('[multiorg] backend no respondió /api/health/ tras el warmup; continúo igual.')
}

export default async function globalSetup() {
  await warmupBackend()

  if (process.env.QA_SKIP_SEED === '1') {
    console.log('[multiorg] QA_SKIP_SEED=1 → se omite el seed (se asume ya sembrado).')
    return
  }
  const here = path.dirname(fileURLToPath(import.meta.url))
  const backend = path.resolve(here, '..', 'backend')
  const py = process.env.QA_PYTHON || path.join(backend, '.venv', 'Scripts', 'python.exe')

  console.log('[multiorg] Seed (--org=all)…')
  // execFileSync con array de args: sin shell, sin interpolación (no command injection).
  execFileSync(py, ['manage.py', 'seed_demo_data', '--org=all'], {
    cwd: backend,
    stdio: 'inherit',
    env: {
      ...process.env,
      DJANGO_DEBUG: '1',
      SQLITE_DB_NAME: process.env.SQLITE_DB_NAME || 'e2e.sqlite3',
    },
  })
}
