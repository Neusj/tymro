import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'
import dotenv from 'dotenv'
import { apiLogin, creds } from './fixtures/data.js'

dotenv.config()

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

const FIXTURES_PATH = path.join(__dirname, '.fixtures.json')

// Ejecuta el comando de seed (QA_SEED_CMD) desde la raíz del repo y extrae la
// línea machine-readable `TYMRO_E2E_FIXTURES={...}` que imprime el comando Django.
// El resultado se persiste en .fixtures.json para que lo lean los tests.
export function runSeedOnly() {
  const cmd = process.env.QA_SEED_CMD
  if (process.env.QA_SKIP_SEED === '1' || !cmd) {
    console.log('[seed] QA_SEED_CMD vacío o QA_SKIP_SEED=1 → se omite el seed.')
    if (!fs.existsSync(FIXTURES_PATH)) {
      throw new Error(
        'No hay .fixtures.json y el seed está desactivado. Corre el seed una vez ' +
        'con QA_SEED_CMD definido, o crea e2e/.fixtures.json manualmente.',
      )
    }
    return JSON.parse(fs.readFileSync(FIXTURES_PATH, 'utf8'))
  }

  console.log(`[seed] Ejecutando: ${cmd}`)
  const out = execSync(cmd, { cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  const line = out.split(/\r?\n/).find((l) => l.startsWith('TYMRO_E2E_FIXTURES='))
  if (!line) {
    console.error(out)
    throw new Error('El seed no imprimió la línea TYMRO_E2E_FIXTURES=. ¿Imagen del backend actualizada?')
  }
  const fixtures = JSON.parse(line.slice('TYMRO_E2E_FIXTURES='.length))

  // Overrides por env tienen prioridad (multitenancy, etc.).
  if (process.env.QA_FOREIGN_CLASS_ID) {
    fixtures.foreign = { ...(fixtures.foreign || {}), class_id: Number(process.env.QA_FOREIGN_CLASS_ID) }
  }
  if (process.env.QA_FOREIGN_ORG_ID) {
    fixtures.foreign = { ...(fixtures.foreign || {}), org_id: Number(process.env.QA_FOREIGN_ORG_ID) }
  }

  fs.writeFileSync(FIXTURES_PATH, JSON.stringify(fixtures, null, 2))
  console.log(`[seed] Fixtures escritos (org ${fixtures.org_slug}).`)
  return fixtures
}

// Token de gym_admin (lo reusa el spec de QR para pedir el QR vigente). El login
// del ALUMNO no se hace aquí: lo hace el setup project (00-auth.setup.js), porque
// el backend rota el token en cada login y queremos una única sesión de alumno.
async function captureGymAdminToken() {
  const gymAdmin = await apiLogin(creds.gymAdmin.username, creds.gymAdmin.password)
  await gymAdmin.ctx.dispose()
  console.log(`[setup] Token de gym_admin capturado (${gymAdmin.user?.username}).`)
  return { gymAdmin: gymAdmin.token }
}

export default async function globalSetup() {
  const fixtures = runSeedOnly()
  fixtures.tokens = await captureGymAdminToken()
  fs.writeFileSync(FIXTURES_PATH, JSON.stringify(fixtures, null, 2))
}
