import { test, expect } from '@playwright/test'
import { apiContext, apiLogin, getOrgIdBySlug, HOSTS, superadminToken } from './_helpers.js'

const uniq = () => `${Date.now()}${Math.floor(Math.random() * 1e6)}`

function emails(data) {
  const list = Array.isArray(data) ? data : data.results || []
  return list.map((u) => u.email)
}

test.describe('CRUD de usuarios y aislamiento multi-tenant', () => {
  let token
  let r2bId
  let gymTestId

  test.beforeAll(async () => {
    token = await superadminToken()
    r2bId = await getOrgIdBySlug(token, 'r2b-qa')
    gymTestId = await getOrgIdBySlug(token, 'gym-test')
  })

  test('superadmin crea un profesor en r2b-qa y aparece sólo en esa org', async () => {
    const email = `prof-${uniq()}@r2b.local`
    const ctx = await apiContext({ host: HOSTS.apex, token })

    const created = await ctx.post('users/', { data: { email, role: 'teacher', password: 'Passw0rd2026', organization: r2bId } })
    expect(created.status(), JSON.stringify(await created.json())).toBe(201)

    const inR2b = await ctx.get(`users/?organization_id=${r2bId}`)
    expect(emails(await inR2b.json())).toContain(email)

    const inGymTest = await ctx.get(`users/?organization_id=${gymTestId}`)
    expect(emails(await inGymTest.json())).not.toContain(email)

    await ctx.dispose()
  })

  test('superadmin puede editar y borrar un usuario de una org', async () => {
    const email = `tmp-${uniq()}@r2b.local`
    const ctx = await apiContext({ host: HOSTS.apex, token })

    const created = await ctx.post('users/', { data: { email, role: 'student', password: 'Passw0rd2026', organization: r2bId } })
    const id = (await created.json()).id

    const patched = await ctx.patch(`users/${id}/`, { data: { first_name: 'Editado' } })
    expect(patched.status()).toBe(200)
    expect((await patched.json()).first_name).toBe('Editado')

    const removed = await ctx.delete(`users/${id}/`)
    expect(removed.status()).toBe(204)
    await ctx.dispose()
  })

  test('gym_admin de r2b lista SÓLO usuarios de su org', async () => {
    const { token: gymToken } = await apiLogin({ host: HOSTS.r2b, email: 'gymadmin@tymro.local', password: 'gymadmin123' })
    const ctx = await apiContext({ host: HOSTS.r2b, token: gymToken })
    const res = await ctx.get('users/')
    expect(res.status()).toBe(200)
    const data = await res.json()
    const list = Array.isArray(data) ? data : data.results || []
    // Todos los usuarios listados son de r2b-qa (organization == r2bId).
    for (const u of list) {
      expect(u.organization).toBe(r2bId)
    }
    await ctx.dispose()
  })

  test('gym_admin de r2b NO puede ver un usuario de gym-test (404)', async () => {
    // Tomamos un id de usuario de gym-test (como superadmin).
    const sup = await apiContext({ host: HOSTS.apex, token })
    const gymTestUsers = await sup.get(`users/?organization_id=${gymTestId}`)
    const data = await gymTestUsers.json()
    const list = Array.isArray(data) ? data : data.results || []
    expect(list.length).toBeGreaterThan(0)
    const foreignId = list[0].id
    await sup.dispose()

    const { token: gymToken } = await apiLogin({ host: HOSTS.r2b, email: 'gymadmin@tymro.local', password: 'gymadmin123' })
    const ctx = await apiContext({ host: HOSTS.r2b, token: gymToken })
    const res = await ctx.get(`users/${foreignId}/`)
    expect(res.status()).toBe(404)
    await ctx.dispose()
  })

  test('superadmin lista superadmins por role=superadmin (sin organization_id)', async () => {
    const ctx = await apiContext({ host: HOSTS.apex, token })
    const res = await ctx.get('users/?role=superadmin')
    expect(res.status()).toBe(200)
    const data = await res.json()
    const list = Array.isArray(data) ? data : data.results || []
    expect(list.length).toBeGreaterThan(0)
    for (const u of list) {
      expect(u.role).toBe('superadmin')
      expect(u.organization).toBeNull()
    }
    await ctx.dispose()
  })
})
