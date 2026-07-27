import { describe, it, expect } from 'vitest'

// SIN mock de axios: se importa el cliente real para inspeccionar la config
// efectiva de las instancias. Un mock de `axios.create` haría que el test
// afirmara sobre el mock y no sobre lo que la app usa en runtime.
import api, { publicApi } from './client'

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
