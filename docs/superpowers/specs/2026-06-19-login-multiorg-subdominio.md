# Spec: Login multi-org por subdominio + email único por org + username auto-generado

**Fecha:** 2026-06-19
**Branch:** deploy/railway-prod
**Estado:** Aprobado para implementación.

## Objetivo

El email pasa a ser la clave de login, **única dentro de cada organización** (no global). La
organización se resuelve del **subdominio del Host**. El campo `username` deja de pedirse:
sobrevive como identificador interno de Django (`USERNAME_FIELD`, único global) pero se
**auto-genera** y se oculta de UI y API. El mismo email puede existir en ORG A y ORG B.

Bugs que se corrigen de paso:
- Username como namespace global (ya no se pide ni colisiona entre orgs).
- Email sin validar en alta admin (ahora obligatorio y único por org).

## Decisiones de arquitectura

1. **Resolución de tenant por Host.** `OrganizationMiddleware` lee `request.get_host()`
   (que respeta `USE_X_FORWARDED_HOST=True`), le quita el puerto y le resta `BASE_DOMAIN`
   (env; dev `localhost`, prod `tymroapp.com`). El label restante es el subdominio.
   - Host = apex/plataforma (`BASE_DOMAIN` pelado, `app.<BASE_DOMAIN>`, `localhost`,
     `127.0.0.1`) → `request.organization = None` (contexto plataforma, superadmins).
   - Subdominio presente → `Organization.objects.filter(subdomain=label, is_active=True)`.
     No encontrado → **404** "Organización no encontrada".
   - Allowlist de paths que NO exigen org válida: `/admin/`, `/api/health/`, `/static/`,
     `/media/`, y el catch-all del SPA (sirve index.html en cualquier host).
   - `request.organization` queda disponible para login y para el guard de consistencia.

2. **Email único por organización (case-insensitive).** En `CustomUser`:
   - `UniqueConstraint(Lower('email'), 'organization', name='uniq_email_per_org')` para
     usuarios de organización.
   - `UniqueConstraint(Lower('email'), condition=Q(organization__isnull=True),
     name='uniq_email_platform')` para superadmins (org NULL, donde un `unique_together`
     no validaría nada). Cubre el caso plataforma sin agujeros.
   - El serializer también valida explícitamente (mensaje 400 limpio, no IntegrityError 500).

3. **Username auto-generado y oculto.** `username` sigue `unique=True` global (lo exige
   `AbstractUser`). Se genera en `CustomUser.save()` cuando viene vacío como
   `uuid4().hex` (32 hex; pasa el validador de username de Django — `:` y otros separadores
   no son válidos). Se elimina de los `fields` del serializer y de toda la UI.

4. **Login por email.** `LoginView` recibe `{email, password}`. Resuelve el usuario por
   `email__iexact` dentro de `request.organization` (o entre superadmins si plataforma),
   valida `check_password` + `is_active`, y rota el token (comportamiento actual). Ya no usa
   `authenticate()` (lookup manual por org). Acepta `username` como alias legacy del payload
   (se trata como email) para resiliencia. Mantiene throttle scope `login`.

5. **Guard de consistencia org ↔ subdominio.** Un usuario de organización sólo puede operar
   en el subdominio de SU organización; mismatch → 403. Superadmin/plataforma exentos.
   Consecuencia: cada spec corre en el subdominio de su org.

6. **Flujos por email scopeados por org.** `password-reset`, registro público y verificación
   de email dejan de asumir email global: se acotan a `request.organization` (o a la org del
   contexto público) para no quedar ambiguos con emails repetidos entre orgs.

7. **E2E local sobre `*.localhost`.** Chromium resuelve `*.localhost` → 127.0.0.1. Un solo
   backend (`:8000`) y un solo Vite (`:5173`) sirven todos los hosts; cada proyecto Playwright
   usa un `baseURL` distinto (`r2b-qa.localhost`, `gym-test.localhost`, apex `localhost`).
   La infra wildcard de QA/prod (`*.tymroapp.com` DNS+TLS+routing) queda parametrizada por env
   y documentada como handoff; NO se activa en este cambio.

## Cambios por capa

### Backend
- `core/models.py`: `Organization.subdomain` (`CharField(max_length=50, unique=True,
  null=True, blank=True)`, validador minúsculas `^[a-z0-9-]+$`, reservados
  `{admin, app, www, api, qa, static, media, localhost}`). `CustomUser`: las 2
  `UniqueConstraint` de email; `save()` auto-genera username.
- `core/middleware.py` (nuevo): `OrganizationMiddleware`.
- `tymro/settings.py`: registrar el middleware; `BASE_DOMAIN` env (default `localhost`);
  `ALLOWED_HOSTS += ['.localhost']`; `CORS_ALLOWED_ORIGIN_REGEXES += r'^http://[a-z0-9-]+\.localhost:5173$'`;
  `CSRF_TRUSTED_ORIGINS += 'http://*.localhost:5173'`; throttle de login override por env
  (para que el E2E local no tope 5/min).
- `core/views.py`: `LoginView` por email + org; guard de consistencia; scope por org en
  `PasswordResetRequestView`, `PublicRegisterView`, `PublicVerifyEmailView`.
- `core/serializers.py`: `CustomUserSerializer` sin `username` en `fields`; `email` requerido;
  `validate()` con unicidad de email por org; `OrganizationSerializer` expone `subdomain`
  (write para superadmin, con validación de formato/reservados/unicidad).
- Migración `0025`: agrega `subdomain` (null=True) → data-migration que lo puebla desde `slug`
  garantizando unicidad → `AlterField` a `null=False`; agrega las 2 constraints de email;
  backfill defensivo de `username` (uuid) para filas sin él.

### Frontend
- `pages/LoginPage.jsx`: campo **Email** (type email), sin username, sin org. Postea
  `{email, password}`.
- `api/client.js`: `authApi.login` envía `{email, password}`. `baseURL` sigue `/api`.
- `vite.config.js`: `allowedHosts += ['.localhost', '.tymroapp.com']`; proxy `/api` y `/media`
  con `xfwd: true` y `changeOrigin: false` (preserva el Host/`X-Forwarded-Host` del subdominio).
- `SuperadminUsersPage`, `SuperadminPlatformPage`, `GymAdminUsersPage`: quitar columna y campo
  **Username**; mostrar **Nombre+Apellido + Email**; Email requerido en crear/editar.

### Seed (`seed_demo_data.py`)
- `--org=all` seedea `r2b-qa`, `gym-test`, `e2e-gym`, cada una con `subdomain` propio.
- Email compartido a propósito entre orgs: `juan@demo.local` como student en `r2b-qa` y como
  teacher en `gym-test` (caso clave del cambio).
- Usuarios con `email` único por org y `username` auto. El payload `TYMRO_E2E_FIXTURES=` se
  extiende con `orgs` (slug→subdomain), emails de login por rol y el email compartido.

### E2E (`e2e/`)
- `playwright.config.js`: proyectos nuevos **superadmin** (apex `localhost`), **gym-test**
  (`gym-test.localhost`) y **e2e-gym** (`e2e-gym.localhost`), cada uno con su `baseURL`,
  `storageState` y setup. Se conservan/adaptan student/teacher (org `r2b-qa`).
- `global-setup.js`: `QA_SEED_CMD` apunta al seed local (venv) con `--org=all`; captura tokens
  por email en el subdominio correcto.
- `fixtures/data.js`: `apiLogin` postea `{email, password}` contra el `apiURL` del subdominio;
  `creds` por email.
- Specs nuevos (≥35 casos) cubriendo: login por email+subdominio; mismo email en 2 orgs OK;
  email duplicado misma org → 400; crear org con subdominio mapea; subdominio inexistente →
  404; aislamiento (login r2b-qa no ve gym-test); username ausente en API y UI; CRUD usuarios
  multitenancy; password reset por email scoped por org.

## Edge cases
- Superadmin (org NULL): login en apex; email único global entre superadmins.
- Subdominio reservado: ninguna org puede tomar `admin/app/www/api/qa/...`.
- Email case-insensitive: `Juan@x.com` == `juan@x.com` dentro de la misma org.
- Cambio de email de un usuario: el username interno no cambia (sigue único).
- Migración contra data existente: backfill idempotente; contra seed nuevo es no-op.

## Verificación / Done
- `python manage.py check` y `migrate` sin errores.
- Suite **pytest** del backend en verde (incluye nuevos tests de unicidad/middleware/login).
- Stack local arriba (backend `:8000`, Vite `:5173`), seed `--org=all` aplicado.
- Suite **E2E** nueva en **verde 35+/35+** corriendo contra backend real (sin mocks),
  con salida real adjunta.
- Commit: "Arquitectura: login multi-org por subdominio + email único por org + username auto-generado".
- Listo para push a `deploy/railway-prod` (no se pushea hasta confirmación).

## Fuera de alcance (handoff)
- Provisión de wildcard DNS + TLS + routing Cloudflare/Nginx para `*.tymroapp.com` en QA/prod.
  El código queda parametrizado por `BASE_DOMAIN`; se entrega checklist.
