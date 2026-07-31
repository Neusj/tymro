# CLAUDE.md — Raíz (TYMRO)

Monorepo del SaaS de gestión de gimnasios: `backend/` (Django + DRF) y `frontend/` (React + Vite).

**Este archivo cubre SOLO lo transversal de raíz.** Las reglas de cada mitad viven en
[backend/CLAUDE.md](backend/CLAUDE.md) (multitenancy, servicios, roles, permisos) y
[frontend/CLAUDE.md](frontend/CLAUDE.md) (cliente axios, auth, rutas por rol). No duplicar acá.

## ⚠️ Deploy: `deploy/railway-prod` es PRODUCCIÓN

- Railway despliega automáticamente desde la rama **`deploy/railway-prod`** (que además es la
  rama principal de este repo).
- **"Probar en Railway" = deploy REAL a producción, con cliente activo usando la app.** No hay
  staging aparte. Mergear y pushear a esa rama es publicar.
- **Pre-deploy obligatorio:** `python manage.py migrate` (aplicar migraciones antes de que el
  código nuevo tome tráfico).

## Topología de producción: single-service

- Un **único servicio** en Railway construido con **`Dockerfile.prod`**: **gunicorn + WhiteNoise**
  sirven **la API y la SPA juntas** desde el mismo proceso.
- Por lo tanto hay **UN SOLO proxy** delante (el edge de Railway) → **`NUM_PROXIES = 1`**.
- **`frontend/nginx.conf` (con su `proxy_pass`) es SOLO para `docker-compose` local.** No describe
  producción. **Confundirlo con la topología real ya causó un bug de seguridad** (cadena de
  proxies mal contada → `X-Forwarded-For` manipulable). Antes de razonar sobre proxies, IPs
  reales o throttling, asumir single-service, no nginx.

## Dominio

- Producción es **`https://app.tymroapp.com`** (subdominio).
- El **apex `tymroapp.com` no resuelve** y no tiene TLS válido. **Usar siempre el subdominio**
  en configuración, pruebas, links y `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`.

## Tests

```bash
cd backend  && python -m pytest     # suite Django (core/tests/)
cd frontend && npm run test          # vitest (unitarios, jsdom)
cd e2e      && npm test              # Playwright (flujo end-to-end)
```

- Postgres local de verificación (para correr la suite contra Postgres, no SQLite):
  contenedor **`tymro-pg-verify`**, imagen `postgres:16`, en **`127.0.0.1:55432`**,
  credenciales `tymro` / `tymro` / db `tymro`.

## Email

- **El correo sale por la API HTTPS de Resend, no por SMTP:** Railway **bloquea SMTP saliente**.
  No introducir backends SMTP ni asumir que `send_mail` por puerto 587 funciona en prod.

## Revisión de seguridad

- El agente **`tymro-security-reviewer`** ([.claude/agents/tymro-security-reviewer.md](.claude/agents/tymro-security-reviewer.md))
  audita aislamiento cross-tenant y autorización.
- **Se invoca MANUALMENTE y por nombre** después de tocar `core/views.py`, `core/serializers.py`,
  `core/permissions.py` o cualquier ViewSet/APIView/endpoint nuevo. La configuración de sesión
  **no dispara agentes por su cuenta**, así que si no se lo pide explícitamente, no corre.
- Forma de correrlo: pedir "revisá esto con el agente `tymro-security-reviewer`" (o lanzarlo con
  la herramienta Agent usando `subagent_type: tymro-security-reviewer`).
