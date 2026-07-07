# PWA: experiencia de instalación + auto-update verificado

**Fecha:** 2026-07-07
**Rama:** `feat/pwa-install-experience` (desde `deploy/railway-prod`; NO se toca esa rama)
**Alcance:** solo frontend/PWA. No se toca login (lógica/auth), `client.js`, resolución de organización/tenant, ni pagos.

## Objetivo

1. Botón "Instalar app" / "Usar como app" visible y no invasivo:
   - Android/escritorio (Chromium): capturar `beforeinstallprompt`, prevenir el default y disparar el prompt nativo al tocar el botón.
   - iOS Safari (no dispara `beforeinstallprompt`): detectar iOS y mostrar un modal con pasos manuales (Compartir → "Agregar a pantalla de inicio").
   - Ocultar el botón si la app ya corre instalada (`display-mode: standalone`) o si ya fue instalada.
   - Disponible tanto en el header autenticado como en la landing (pantalla de login).
2. Auto-update silencioso: mantener `registerType: 'autoUpdate'`. Garantizar que una versión nueva del SW se active y la app tome los cambios limpiamente al reabrir, sin pantalla rota ni caché vieja. Sin toast ni UI de "actualizar".
3. Sin dependencia nueva de subdominio/tenant. Sin tocar `client.js`/auth/login/pagos.

## Hallazgos clave del código

- El header global vive en `src/components/layout/AppLayout.jsx` (sticky). La landing de cada subdominio ES `src/pages/LoginPage.jsx` (`/` redirige a `/login` sin sesión; no hay landing de marketing aparte).
- **Cada ruta envuelve su propio `<ShellRoute>` → `<AppLayout>`**, así que `AppLayout` se **remonta en cada navegación**. `beforeinstallprompt` es un evento **de una sola vez**: un listener atado solo en el montaje del componente lo perdería tras un remontaje. Por eso la captura debe ser un **singleton global**, no un listener por componente.
- La config PWA ya está en `autoUpdate` con `skipWaiting`, `clientsClaim`, `cleanupOutdatedCaches` (equivale a actualización silenciosa + recarga limpia; confirmado en docs de vite-plugin-pwa).
- Tests: vitest + jsdom, `include: ['src/**/*.{test,spec}.{js,jsx}']`. Patrón de componente/test existente en `RutReminderBanner`, patrón de modal en `ConfirmDialog` (`createPortal` + `useBodyScrollLock` + Escape).

## Arquitectura (unidades nuevas, aisladas en `src/pwa/`)

### 1. `src/pwa/installPrompt.js` — singleton de captura (sin React)
- Auto-inicializa al importarse (idempotente, guard de `window`).
- Escucha global y una sola vez:
  - `beforeinstallprompt` → `preventDefault()` + bufferiza el evento diferido + notifica.
  - `appinstalled` → marca `installed`, limpia el buffer + notifica.
- API: `getInstallState()` → `{ deferredPrompt, installed }`; `subscribe(cb)` → unsubscribe; `clearDeferredPrompt()`; `resetInstallState()` (solo tests).
- Se importa por efecto en `main.jsx` (una línea) para capturar el evento antes de que React monte. No toca auth/login/pagos.

### 2. `src/pwa/usePwaInstall.js` — binding React del singleton
- `useState(getInstallState)` + `useEffect(subscribe)` → refleja el estado aun si el evento llegó antes del montaje (lee del buffer).
- Calcula una vez: `isStandalone` (`matchMedia('(display-mode: standalone)').matches || navigator.standalone === true`) e `isIOS` (UA `iphone|ipad|ipod` + heurística iPadOS-como-Mac vía `maxTouchPoints`).
- Devuelve `{ canInstall, installed, isStandalone, isIOS, promptInstall }`.
- `promptInstall()`: `deferredPrompt.prompt()`, espera `userChoice`, limpia el buffer (Chrome solo permite un uso).

### 3. `src/components/InstallAppButton.jsx` — UI (botón + modal iOS)
- Visibilidad: `return null` si `isStandalone || installed`, o si `!canInstall && !isIOS`.
- Click: `canInstall` → prompt nativo; `isIOS` → abre modal instructivo (Compartir → "Agregar a pantalla de inicio" → Agregar), con ícono de compartir y pasos numerados. Modal con `createPortal` + `useBodyScrollLock` + Escape (patrón `ConfirmDialog`).
- Prop `variant`: `'header'` (pill compacto, label oculto en móvil) y `'landing'` (más prominente). Estilo con tokens de marca (skill frontend-design).

### 4. `src/pwa/pwaOptions.js` — extracción testeable de la config
- Se mueve el objeto de opciones de `VitePWA({...})` a este módulo (`export const pwaOptions`). `vite.config.js` pasa a `VitePWA(pwaOptions)`. **Comportamiento idéntico**; se mantiene `autoUpdate` + `skipWaiting` + `clientsClaim` + `cleanupOutdatedCaches`.

## Puntos de montaje (aditivos)
- `AppLayout.jsx` header, cluster derecho, antes de "Cerrar sesión": `<InstallAppButton variant="header" />`.
- `LoginPage.jsx`, bajo el form: `<InstallAppButton variant="landing" />`. Solo JSX; sin tocar `onSubmit`/`login()`/estado.

## Auto-update (requisito 2)
La config ya cumple. No se cambia comportamiento; se agrega **test de regresión** que falla si `autoUpdate`→`prompt` o si se quitan `skipWaiting`/`clientsClaim`/`cleanupOutdatedCaches`. Sin toast, sin UI de actualizar.

## Tests (TDD, vitest/jsdom)
- `src/pwa/usePwaInstall.test.jsx`: captura `beforeinstallprompt` (con `preventDefault`); detección `standalone`; detección iOS; `appinstalled` oculta.
- `src/components/InstallAppButton.test.jsx` (mock del hook): aparece con `canInstall`; oculto en `standalone`; oculto si instalada; iOS muestra instructivo; sin soporte → oculto; click dispara `promptInstall`.
- `src/pwa/pwaOptions.test.js`: `registerType === 'autoUpdate'` + `skipWaiting`/`clientsClaim`/`cleanupOutdatedCaches` true.
- `npm run build` OK.

## Fuera de alcance
`client.js`, auth, lógica de login, resolución de org/tenant, pagos. `deploy/railway-prod`. `main.jsx` solo recibe un `import` de efecto PWA.

## Verificación
Suite vitest verde + `npm run build` OK + corrida en QA (dev/preview) confirmando que el botón aparece/oculta correctamente, antes de proponer merge.
