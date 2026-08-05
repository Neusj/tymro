import { describe, it, expect, beforeEach, afterEach } from 'vitest'

// SIN mock de axios: se importa el cliente real para inspeccionar la config
// efectiva de las instancias. Un mock de `axios.create` haría que el test
// afirmara sobre el mock y no sobre lo que la app usa en runtime.
import api, { advanceClassWindowsApi, authApi, dashboardApi, importsApi, publicApi } from './client'

// El landmine que cubren estos tests: sin `timeout`, axios usa el default 0 =
// esperar indefinidamente. Una petición que nunca responde (red caída, proxy
// colgado) deja la app esperando hasta el timeout TCP del SO, que puede ser de
// minutos. Con 10s el error llega a la app y la UI puede reaccionar.
const REQUEST_TIMEOUT_MS = 10000

describe('config de las instancias axios de client.js', () => {
  it('la instancia autenticada corta una petición colgada a los 10s', () => {
    expect(api?.defaults?.timeout).toBe(REQUEST_TIMEOUT_MS)
  })

  it('la instancia pública corta una petición colgada a los 10s', () => {
    expect(publicApi?.defaults?.timeout).toBe(REQUEST_TIMEOUT_MS)
  })
})

// El default de 10s es correcto para la app, pero corta endpoints que tardan
// legítimamente más. Estos tests miran el `config` que recibe el ADAPTER: es la
// config ya mergeada por axios (defaults + override por request), o sea el
// valor que de verdad gobierna el corte en runtime.
describe('timeout por endpoint', () => {
  const originalAdapter = api.defaults.adapter
  let seen

  beforeEach(() => {
    seen = []
    api.defaults.adapter = (config) => {
      seen.push(config)
      return Promise.resolve({
        data: {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
        request: {},
      })
    }
  })

  afterEach(() => {
    api.defaults.adapter = originalAdapter
  })

  it('login espera 40s: en un cold start de Railway cortar a los 10s quema un intento del throttle', async () => {
    await authApi.login({ email: 'ana@gym.cl', password: 'secreta' })

    expect(seen).toHaveLength(1)
    expect(seen[0].url).toBe('/login/')
    expect(seen[0].timeout).toBe(40000)
    // El override es un tercer argumento (config), no desplaza al body: las
    // credenciales tienen que seguir viajando intactas.
    expect(JSON.parse(seen[0].data)).toEqual({ email: 'ana@gym.cl', password: 'secreta' })
  })

  it('la validación del importador espera 60s: parsea el XLSX entero antes de responder', async () => {
    const file = new File(['col1,col2'], 'usuarios.xlsx')
    await importsApi.validate('users', file)

    expect(seen).toHaveLength(1)
    expect(seen[0].url).toBe('/imports/users/validate/')
    expect(seen[0].timeout).toBe(60000)
  })

  it('el commit del importador espera 60s: escribe fila por fila dentro de la transacción', async () => {
    const file = new File(['col1,col2'], 'usuarios.xlsx')
    await importsApi.commit('users', file, 'tok-preview')

    expect(seen).toHaveLength(1)
    expect(seen[0].url).toBe('/imports/users/commit/')
    expect(seen[0].timeout).toBe(60000)
    // El commit necesita el MISMO archivo + el token de previsualización: el
    // override no puede haber desplazado el FormData.
    expect(seen[0].data.get('file')).toBeInstanceOf(File)
    expect(seen[0].data.get('token')).toBe('tok-preview')
  })

  it('el robot de ventana rodante (botón "Actualizar clases") espera 60s: corre síncrono en el request con solo 3 workers gunicorn en prod', async () => {
    await advanceClassWindowsApi.run()

    expect(seen).toHaveLength(1)
    expect(seen[0].url).toBe('/advance-class-windows/')
    expect(seen[0].timeout).toBe(60000)
    // El body NO se lee en el backend (la org sale del actor): el front tampoco manda uno.
    expect(seen[0].data).toBeUndefined()
  })

  it('el resto de los endpoints conserva el default de 10s', async () => {
    await authApi.me()
    await dashboardApi.summary()

    expect(seen.map((config) => [config.url, config.timeout])).toEqual([
      ['/me/', REQUEST_TIMEOUT_MS],
      ['/dashboard/', REQUEST_TIMEOUT_MS],
    ])
  })
})
