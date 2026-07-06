# Diseño — Link de clase de prueba por subdominio de la organización

**Fecha:** 2026-07-05
**Rama:** `fix/trial-link-subdomain`
**Estado:** aprobado por el usuario (diseño); pendiente implementación.

## Problema

El link público de clase de prueba se arma hoy como `FRONTEND_URL/{slug}/clase-gratis`,
lo que en producción produce `https://tymroapp.com/gladiador/clase-gratis`. Tras el
refactor a multi-tenant **por subdominio**, el apex (`tymroapp.com`) resuelve a
contexto plataforma (`request.organization = None`) y el login queda acotado a la
org del subdominio, por lo que ese link es incoherente/roto para el gimnasio.

La URL debe construirse sobre el subdominio de la organización:
`https://{org.subdomain}.{BASE_DOMAIN}/clase-gratis`.

Diagnóstico completo y evidencia: ver el informe de auditoría de 2026-07-05.

## Objetivos

1. Un **helper centralizado único** que construya la URL pública a partir de una
   `Organization`, usando `org.subdomain` + `BASE_DOMAIN` + esquema/puerto de
   `FRONTEND_URL`.
2. Reemplazar las **dos construcciones duplicadas** actuales (serializer + comando
   de followup) para que usen el helper.
3. El flujo público resuelve la org por el **subdominio del host**, no por el slug
   en el path. El email de verificación y el de reset de contraseña usan la misma
   base por subdominio.
4. **Tests que asserten el VALOR** de la URL (host = subdominio esperado), en el
   serializer y en el comando de followup.

No-objetivos: cambiar modelos/migraciones, tocar variables de Railway o producción,
introducir variables de entorno nuevas.

## Decisiones (confirmadas con el usuario)

- **Esquema/puerto:** derivados de `FRONTEND_URL`; el host se arma con
  `{subdomain}.{BASE_DOMAIN}`. Así prod → `https://…tymroapp.com`, QA local →
  `http://….localhost:5173`, sin variables nuevas.
- **Links viejos** (`/{slug}/clase-gratis` en apex): la ruta del frontend se
  conserva como **redirección** al subdominio (flyers/QR ya impresos siguen
  funcionando degradados), no se elimina.
- **Reset password** (`views.py:548`): **incluido** en este cambio (mismo problema
  de subdominio para usuarios de una org).
- **Verificación local:** `pytest` (core/tests) + harness E2E de API por subdominio;
  sin browser E2E obligatorio.

## Arquitectura

### A. Helper — nuevo `backend/core/services/public_urls.py`

Fuente única de verdad. Interfaz:

- `organization_public_base_url(organization) -> str`: devuelve `scheme://host[:port]`.
  Host = `{subdomain}.{BASE_DOMAIN}`; esquema y puerto salen de `FRONTEND_URL`. Si la
  org no tiene subdominio o es `None` (contexto plataforma), cae al host de
  `FRONTEND_URL` (apex).
- `trial_signup_url(organization) -> str`: `{base}/clase-gratis`. Fallback defensivo:
  si la org (legacy) no tiene subdominio, usa el link viejo `FRONTEND_URL/{slug}/clase-gratis`
  (lo captura la ruta de redirect).

```python
from urllib.parse import urlsplit
from django.conf import settings

def organization_public_base_url(organization):
    parts = urlsplit(settings.FRONTEND_URL)
    subdomain = getattr(organization, 'subdomain', None)
    if not subdomain:
        return settings.FRONTEND_URL.rstrip('/')
    host = f'{subdomain}.{getattr(settings, "BASE_DOMAIN", "localhost")}'
    if parts.port:
        host = f'{host}:{parts.port}'
    return f'{parts.scheme or "https"}://{host}'

def trial_signup_url(organization):
    if getattr(organization, 'subdomain', None):
        return f'{organization_public_base_url(organization)}/clase-gratis'
    return f'{settings.FRONTEND_URL.rstrip("/")}/{organization.slug}/clase-gratis'
```

### B. Uso del helper (elimina duplicación)

- `core/serializers.py` `OrganizationSerializer.get_public_registration_url` →
  `return trial_signup_url(obj)`.
- `core/management/commands/send_trial_followups.py` → `signup_link = trial_signup_url(org)`.
- `core/views.py` `PublicRegisterView` verify_link →
  `f"{organization_public_base_url(organization)}/verify-email?uid={uid}&token={token}"`.
- `core/views.py` `PasswordResetRequestView` reset_link →
  `f"{organization_public_base_url(user.organization)}/reset-password?uid={uid}&token={token}"`
  (usuario de plataforma → `user.organization is None` → apex, correcto).

### C. Resolución de org por subdominio (con fallback a slug)

Nuevo helper en `core/views.py`, usado por `PublicInviteValidateView` y
`PublicRegisterView`:

```python
def _resolve_public_org(request, slug=None):
    org = getattr(request, 'organization', None)   # lo setea OrganizationMiddleware
    if org is not None:
        return org if org.public_registration_enabled else None
    if slug:                                        # back-compat: apex + slug (redirect)
        return _resolve_invite_org(slug)
    return None
```

- Flujo nuevo (host = subdominio, sin slug) → resuelve por `request.organization`.
- Back-compat (host = apex + slug) → `_resolve_invite_org(slug)`.
- En un subdominio con `public_registration_enabled=False` → 404 (respeta el switch).
- Tests actuales usan `Host: testserver` (→ org `None`) + slug, así que siguen verdes.

### D. Frontend

- `frontend/src/App.jsx`:
  - `/clase-gratis` → `GymPublicRegisterPage` (org por subdominio).
  - `/:slug/clase-gratis` → **nuevo** `TrialLinkRedirect`: `validateInvite({slug})` →
    `window.location.replace(data.public_registration_url)`; si inválido, muestra el
    mensaje de link inválido.
- `frontend/src/pages/GymPublicRegisterPage.jsx`: quita `useParams` slug; llama
  `validateInvite()` (sin slug) y `register()` (sin slug).
- `frontend/src/api/client.js`:
  - `validateInvite: async ({ slug } = {}) => publicApi.get('/public/invite/', { params: slug ? { slug } : {} })`.
  - `register`: slug opcional (no lo exige).
- `core/serializers.py` `PublicOrganizationBrandingSerializer`: agrega
  `public_registration_url` (SerializerMethodField vía `trial_signup_url`) para el
  redirect. Sigue sin exponer el token.

### E. Tests (asertan el valor de la URL)

- **Nuevo** `backend/core/tests/test_public_urls.py`:
  - `trial_signup_url(org)` y `OrganizationSerializer(org).data['public_registration_url']`
    == `https://{sub}.tymroapp.com/clase-gratis` con settings shape prod
    (`BASE_DOMAIN=tymroapp.com`, `FRONTEND_URL=https://tymroapp.com`).
  - Shape QA local (`http://{sub}.localhost:5173/clase-gratis`).
  - Fallback sin subdominio → link viejo por slug.
- `backend/core/tests/test_trial_followup.py`: nuevo test que corre el comando y
  assertea que el `{signup_link}` del email == `https://{sub}.tymroapp.com/clase-gratis`
  (override de settings a shape prod).
- `backend/core/tests/test_public_registration.py`:
  - `invite`/`register` por subdominio (`HTTP_HOST='org-1.localhost'`, sin slug) → 200/201,
    usuario creado en esa org.
  - verify-email y reset-password: el link del email usa la base del subdominio.
  - Se conservan los tests por slug (back-compat).

## Impacto

- Sin migraciones. Sin variables de entorno nuevas. Sin cambios en Railway/prod.
- Archivos:
  - Backend: **nuevo** `core/services/public_urls.py`; `core/serializers.py`;
    `core/views.py`; `core/management/commands/send_trial_followups.py`; tests
    (nuevo `test_public_urls.py`, cambios en `test_public_registration.py` y
    `test_trial_followup.py`).
  - Frontend: `App.jsx`; `pages/GymPublicRegisterPage.jsx`; **nuevo**
    `pages/TrialLinkRedirect.jsx`; `api/client.js`.

## Verificación

- `cd backend && python -m pytest -q` → verde (incluye los tests nuevos).
- Corrida dirigida de `test_public_urls.py`, `test_public_registration.py`,
  `test_trial_followup.py`.
- Si es tratable en el entorno: harness E2E de API (`backend/tests/e2e`) del flujo
  trial seteando el `Host` del subdominio (registro → verificación → reserva).
- Trabajo en rama `fix/trial-link-subdomain`; **sin push** hasta validación del usuario.

## Riesgos / mitigaciones

- **Org sin subdominio (legacy):** el helper cae al link viejo por slug (capturado
  por el redirect) → no rompe. `Organization.save()` ya deriva subdomain del slug.
- **TLS wildcard `*.tymroapp.com`** solo cubre subdominios de un nivel → los
  subdominios de tenant son de un nivel (ya se respeta). Infra fuera de alcance.
- **Confiar en `X-Forwarded-Host`** para el subdominio: ya es el comportamiento
  actual del middleware (no lo cambia este trabajo).
