# Trial Link por Subdominio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El link público de clase de prueba (y los emails de verify/reset) se construye sobre el subdominio de la organización (`https://{org.subdomain}.{BASE_DOMAIN}/clase-gratis`) en vez de `FRONTEND_URL/{slug}/clase-gratis`.

**Architecture:** Un helper centralizado (`core/services/public_urls.py`) es la única fuente de verdad de la URL. El backend resuelve la org del flujo público por el subdominio del host (`request.organization`, seteado por `OrganizationMiddleware`) con fallback a `slug` para links viejos. El frontend sirve `/clase-gratis` (org por subdominio) y redirige `/:slug/clase-gratis` (links viejos) al subdominio.

**Tech Stack:** Django 5.0.6 + DRF 3.15.1, pytest/pytest-django; React 18 + Vite (sin test runner en el frontend → verificación por build).

## Global Constraints

- Sin migraciones (no cambian modelos). Sin variables de entorno nuevas. Sin cambios en Railway/producción.
- Rama `fix/trial-link-subdomain`. **Sin `git push`** (la rama `deploy/railway-prod` redepliega al pushear).
- `BASE_DOMAIN` prod = `tymroapp.com`. En tests default = `localhost`; usar la fixture `settings` de pytest-django para overridear a shape prod cuando se aserte el valor de la URL.
- Tests: correr desde `backend/` con `python -m pytest` (config en `pytest.ini` → `tymro.settings_test`, `testpaths=core/tests`).
- TDD: test que falla → mínima implementación → test verde → commit.

---

### Task 1: Helper centralizado `public_urls.py`

**Files:**
- Create: `backend/core/services/public_urls.py`
- Test: `backend/core/tests/test_public_urls.py`

**Interfaces:**
- Produces:
  - `organization_public_base_url(organization) -> str` — `scheme://{subdomain}.{BASE_DOMAIN}[:port]`; si no hay subdominio (o `organization is None`), devuelve el host de `FRONTEND_URL` (apex), sin barra final.
  - `trial_signup_url(organization) -> str` — `{base}/clase-gratis`; si la org no tiene subdominio, `FRONTEND_URL/{slug}/clase-gratis`.

- [ ] **Step 1: Write the failing test**

Create `backend/core/tests/test_public_urls.py`:

```python
"""Valor exacto de las URLs públicas construidas por subdominio de la organización."""
import pytest

from core.services.public_urls import organization_public_base_url, trial_signup_url

pytestmark = pytest.mark.django_db


def _prod(settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'


def test_base_url_prod_shape(make_organization, settings):
    _prod(settings)
    org = make_organization('Gladiador')  # subdomain 'org-1'
    assert organization_public_base_url(org) == 'https://org-1.tymroapp.com'


def test_trial_signup_url_prod_shape(make_organization, settings):
    _prod(settings)
    org = make_organization('Gladiador')
    assert trial_signup_url(org) == 'https://org-1.tymroapp.com/clase-gratis'


def test_trial_signup_url_local_shape(make_organization, settings):
    settings.BASE_DOMAIN = 'localhost'
    settings.FRONTEND_URL = 'http://localhost:5173'
    org = make_organization('Gladiador')
    assert trial_signup_url(org) == 'http://org-1.localhost:5173/clase-gratis'


def test_base_url_falls_back_to_apex_without_subdomain(make_organization, settings):
    _prod(settings)
    org = make_organization('Gladiador')
    org.subdomain = None
    assert organization_public_base_url(org) == 'https://tymroapp.com'
    # trial_signup_url cae al link viejo por slug (lo captura el redirect del frontend).
    assert trial_signup_url(org) == f'https://tymroapp.com/{org.slug}/clase-gratis'


def test_base_url_none_org_is_apex(settings):
    _prod(settings)
    assert organization_public_base_url(None) == 'https://tymroapp.com'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_public_urls.py -v`
Expected: FAIL (ModuleNotFoundError: `core.services.public_urls`).

- [ ] **Step 3: Write minimal implementation**

Create `backend/core/services/public_urls.py`:

```python
"""Fuente única de verdad de las URLs públicas por subdominio de la organización.

El host se arma con ``{subdomain}.{BASE_DOMAIN}``; el esquema y el puerto se toman
de ``FRONTEND_URL`` (https en prod, http://...:5173 en QA local). Una org sin
subdominio (legacy) o ``None`` (contexto plataforma) cae al host de ``FRONTEND_URL``.
"""
from urllib.parse import urlsplit

from django.conf import settings


def organization_public_base_url(organization):
    parts = urlsplit(settings.FRONTEND_URL)
    subdomain = getattr(organization, 'subdomain', None)
    if not subdomain:
        return settings.FRONTEND_URL.rstrip('/')
    base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
    host = f'{subdomain}.{base_domain}'
    if parts.port:
        host = f'{host}:{parts.port}'
    return f'{parts.scheme or "https"}://{host}'


def trial_signup_url(organization):
    if getattr(organization, 'subdomain', None):
        return f'{organization_public_base_url(organization)}/clase-gratis'
    # Org legacy sin subdominio: link viejo por slug (capturado por el redirect).
    return f'{settings.FRONTEND_URL.rstrip("/")}/{organization.slug}/clase-gratis'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest core/tests/test_public_urls.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/public_urls.py backend/core/tests/test_public_urls.py
git commit -m "feat(public-urls): helper de URL pública por subdominio de la org"
```

---

### Task 2: Serializers usan el helper

**Files:**
- Modify: `backend/core/serializers.py` (`OrganizationSerializer.get_public_registration_url` ~141-143; `PublicOrganizationBrandingSerializer` ~1522)
- Test: `backend/core/tests/test_public_urls.py` (añadir)

**Interfaces:**
- Consumes: `trial_signup_url` (Task 1).
- Produces: `OrganizationSerializer(...).data['public_registration_url']` y `PublicOrganizationBrandingSerializer(...).data['public_registration_url']` == `trial_signup_url(org)`.

- [ ] **Step 1: Write the failing test** (append a `test_public_urls.py`)

```python
def test_organization_serializer_url_value(make_organization, settings):
    _prod(settings)
    from core.serializers import OrganizationSerializer
    org = make_organization('Gladiador')
    data = OrganizationSerializer(org).data
    assert data['public_registration_url'] == 'https://org-1.tymroapp.com/clase-gratis'


def test_branding_serializer_exposes_url_not_token(make_organization, settings):
    _prod(settings)
    from core.serializers import PublicOrganizationBrandingSerializer
    org = make_organization('Gladiador')
    data = PublicOrganizationBrandingSerializer(org).data
    assert data['public_registration_url'] == 'https://org-1.tymroapp.com/clase-gratis'
    assert 'public_invite_token' not in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_public_urls.py::test_branding_serializer_exposes_url_not_token -v`
Expected: FAIL (`public_registration_url` no está en la branding serializer / valor viejo por slug).

- [ ] **Step 3: Write minimal implementation**

En `backend/core/serializers.py`, agregar el import cerca de los demás imports de módulo:

```python
from .services.public_urls import trial_signup_url
```

Reemplazar `OrganizationSerializer.get_public_registration_url` (~141-143):

```python
    def get_public_registration_url(self, obj):
        return trial_signup_url(obj)
```

Reemplazar `PublicOrganizationBrandingSerializer` (~1522) para exponer la URL sin el token:

```python
class PublicOrganizationBrandingSerializer(serializers.ModelSerializer):
    """Marca pública del gimnasio para la landing de registro. Solo lectura,
    sin exponer el token ni datos internos. Incluye la URL pública por subdominio
    para que el redirect de links viejos sepa a dónde saltar."""

    public_registration_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['name', 'slug', 'logo', 'primary_color', 'secondary_color', 'public_registration_url']

    def get_public_registration_url(self, obj):
        return trial_signup_url(obj)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/test_public_urls.py core/tests/test_public_registration.py -v`
Expected: PASS (incluye `test_invite_validate_returns_branding_for_valid_slug`, que sigue verde).

- [ ] **Step 5: Commit**

```bash
git add backend/core/serializers.py backend/core/tests/test_public_urls.py
git commit -m "feat(serializers): URL pública por subdominio + branding expone la URL"
```

---

### Task 3: Comando `send_trial_followups` usa el helper

**Files:**
- Modify: `backend/core/management/commands/send_trial_followups.py` (~14-20 imports; ~68-69)
- Test: `backend/core/tests/test_trial_followup.py` (añadir)

**Interfaces:**
- Consumes: `trial_signup_url` (Task 1).

- [ ] **Step 1: Write the failing test** (append a `test_trial_followup.py`, reutiliza `setup`, `_completed_class`, `_trial_attendee`, `_config`)

```python
def test_signup_link_uses_org_subdomain(setup, mailoutbox, settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'])
    _config(
        setup['org'], minutes_after_class_end=30,
        email_subject='Vuelve', email_body='Agenda de nuevo: {signup_link}',
    )

    call_command('send_trial_followups')

    assert len(mailoutbox) == 1
    # setup usa make_organization -> subdomain 'org-1'.
    assert 'https://org-1.tymroapp.com/clase-gratis' in mailoutbox[0].body
    assert 'tymroapp.com/org-1/clase-gratis' not in mailoutbox[0].body  # NO el esquema viejo por slug
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_trial_followup.py::test_signup_link_uses_org_subdomain -v`
Expected: FAIL (el body trae `https://tymroapp.com/org-1/clase-gratis`, esquema viejo).

- [ ] **Step 3: Write minimal implementation**

En `send_trial_followups.py`, agregar import (junto a `from core.models import ...`):

```python
from core.services.public_urls import trial_signup_url
```

Reemplazar las líneas 68-69:

```python
            signup_link = trial_signup_url(org)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/test_trial_followup.py -v`
Expected: PASS (todos, incluido el nuevo).

- [ ] **Step 5: Commit**

```bash
git add backend/core/management/commands/send_trial_followups.py backend/core/tests/test_trial_followup.py
git commit -m "feat(trial-followup): signup_link por subdominio de la org"
```

---

### Task 4: Resolución de org por subdominio en el flujo público

**Files:**
- Modify: `backend/core/views.py` (`_resolve_invite_org` ~606; `PublicInviteValidateView.get` ~634-638; `PublicRegisterView.post` ~651-654)
- Test: `backend/core/tests/test_public_registration.py` (añadir)

**Interfaces:**
- Produces: `_resolve_public_org(request, slug=None) -> Organization | None`.
- Consumes: `request.organization` (lo setea `OrganizationMiddleware`), `_resolve_invite_org` (existente).

- [ ] **Step 1: Write the failing test** (append a `test_public_registration.py`)

```python
# --- 6) Resolución por subdominio (sin slug en el path) -------------------------

def test_invite_by_subdomain_without_slug(api_client, make_organization):
    org = make_organization(name='Cross Santiago')  # subdomain 'org-1'
    ok = api_client.get(INVITE_URL, HTTP_HOST=f'{org.subdomain}.localhost')
    assert ok.status_code == 200
    assert ok.json()['name'] == 'Cross Santiago'


def test_register_by_subdomain_without_slug(api_client, make_organization):
    org = make_organization(name='Cross Santiago')
    from django.contrib.auth import get_user_model
    payload = {
        'first_name': 'Pros', 'last_name': 'Pecto',
        'email': 'pros@example.com', 'password': STRONG_PASSWORD,
    }
    resp = api_client.post(REGISTER_URL, payload, format='json', HTTP_HOST=f'{org.subdomain}.localhost')
    assert resp.status_code == 201, resp.content
    user = get_user_model().objects.get(email__iexact='pros@example.com')
    assert user.organization_id == org.id


def test_disabled_registration_blocks_by_subdomain(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    admin = make_user('admin_a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    api_client.post(f'/api/organizations/{org.id}/set-public-registration/', {'enabled': False}, format='json')
    api_client.force_authenticate(user=None)
    # En el subdominio, con el switch apagado -> 404 (respeta el interruptor).
    assert api_client.get(INVITE_URL, HTTP_HOST=f'{org.subdomain}.localhost').status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_public_registration.py::test_register_by_subdomain_without_slug -v`
Expected: FAIL (404: hoy `register` exige `slug` en el body).

- [ ] **Step 3: Write minimal implementation**

En `backend/core/views.py`, justo después de `_resolve_invite_org` (~620), agregar:

```python
def _resolve_public_org(request, slug=None):
    """Org del flujo público: por subdominio (``request.organization``, lo setea
    OrganizationMiddleware) y, como back-compat para links viejos servidos en el
    apex, por ``slug``. Respeta el interruptor ``public_registration_enabled``."""
    org = getattr(request, 'organization', None)
    if org is not None:
        return org if org.public_registration_enabled else None
    if slug:
        return _resolve_invite_org(slug)
    return None
```

En `PublicInviteValidateView.get` (~634-635) reemplazar la resolución:

```python
    def get(self, request):
        organization = _resolve_public_org(request, request.query_params.get('slug'))
        if organization is None:
            return Response({'detail': 'Link inválido o desactivado.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PublicOrganizationBrandingSerializer(organization, context={'request': request}).data)
```

En `PublicRegisterView.post` (~651-654) reemplazar la resolución:

```python
    def post(self, request):
        organization = _resolve_public_org(request, request.data.get('slug'))
        if organization is None:
            return Response({'detail': 'Link inválido o desactivado.'}, status=status.HTTP_404_NOT_FOUND)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/test_public_registration.py -v`
Expected: PASS (nuevos + los viejos por slug, que usan `Host: testserver` → org `None` → fallback a slug).

- [ ] **Step 5: Commit**

```bash
git add backend/core/views.py backend/core/tests/test_public_registration.py
git commit -m "feat(public): resolver org por subdominio con fallback a slug"
```

---

### Task 5: Emails verify-email y reset-password sobre la base del subdominio

**Files:**
- Modify: `backend/core/views.py` (`PasswordResetRequestView` reset_link ~548; `PublicRegisterView` verify_link ~681)
- Test: `backend/core/tests/test_public_registration.py` (añadir)

**Interfaces:**
- Consumes: `organization_public_base_url` (Task 1).

- [ ] **Step 1: Write the failing test** (append a `test_public_registration.py`)

```python
# --- 7) Base de los emails por subdominio ---------------------------------------

def _prod_settings(settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'


def test_verify_email_link_uses_subdomain(api_client, make_organization, mailoutbox, settings):
    _prod_settings(settings)
    org = make_organization(name='Cross')  # subdomain 'org-1'
    payload = {'first_name': 'Pros', 'email': 'pros@example.com', 'password': STRONG_PASSWORD}
    resp = api_client.post(REGISTER_URL, payload, format='json', HTTP_HOST='org-1.tymroapp.com')
    assert resp.status_code == 201, resp.content
    assert 'https://org-1.tymroapp.com/verify-email?uid=' in mailoutbox[0].body


def test_reset_password_link_uses_subdomain_for_org_user(api_client, make_organization, make_user, mailoutbox, settings):
    _prod_settings(settings)
    org = make_organization(name='Cross')
    make_user('stu', organization=org, role='student', email='stu@example.com')
    resp = api_client.post('/api/password-reset/', {'email': 'stu@example.com'}, format='json', HTTP_HOST='org-1.tymroapp.com')
    assert resp.status_code == 200
    assert 'https://org-1.tymroapp.com/reset-password?uid=' in mailoutbox[0].body


def test_reset_password_link_apex_for_platform_user(api_client, make_user, mailoutbox, settings):
    _prod_settings(settings)
    make_user('root', organization=None, role='superadmin', email='root@example.com')
    resp = api_client.post('/api/password-reset/', {'email': 'root@example.com'}, format='json', HTTP_HOST='tymroapp.com')
    assert resp.status_code == 200
    assert 'https://tymroapp.com/reset-password?uid=' in mailoutbox[0].body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_public_registration.py::test_verify_email_link_uses_subdomain -v`
Expected: FAIL (hoy el link usa `https://tymroapp.com/verify-email`, sin subdominio).

- [ ] **Step 3: Write minimal implementation**

En `backend/core/views.py`, agregar import (junto a los otros imports del módulo):

```python
from core.services.public_urls import organization_public_base_url
```

Reemplazar `reset_link` (~548):

```python
            base = organization_public_base_url(getattr(user, 'organization', None))
            reset_link = f"{base}/reset-password?uid={uid}&token={token}"
```

Reemplazar `verify_link` (~681):

```python
        verify_link = f"{organization_public_base_url(organization)}/verify-email?uid={uid}&token={token}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/test_public_registration.py core/tests/test_auth.py -v`
Expected: PASS (incluye `test_public_registration_happy_path`, cuyo regex `verify-email?uid=...` sigue matcheando).

- [ ] **Step 5: Commit**

```bash
git add backend/core/views.py backend/core/tests/test_public_registration.py
git commit -m "feat(emails): verify-email y reset-password sobre la base del subdominio"
```

---

### Task 6: Frontend — ruta por subdominio + redirect de links viejos

**Files:**
- Modify: `frontend/src/App.jsx` (rutas ~74)
- Modify: `frontend/src/pages/GymPublicRegisterPage.jsx` (quita slug)
- Create: `frontend/src/pages/TrialLinkRedirect.jsx`
- Modify: `frontend/src/api/client.js` (`validateInvite`, `register`)

**Interfaces:**
- Consumes: `GET /api/public/invite/` (sin slug → org por subdominio; con slug → back-compat), `POST /api/public/register/` (sin slug).
- Produces: ruta `/clase-gratis` (registro por subdominio) y `/:slug/clase-gratis` (redirect al subdominio vía `public_registration_url`).

- [ ] **Step 1: `api/client.js` — slug opcional**

En `registrationApi`, reemplazar `validateInvite` y `register`:

```javascript
  validateInvite: async ({ slug } = {}) => {
    const { data } = await publicApi.get('/public/invite/', { params: slug ? { slug } : {} })
    return data
  },
  register: async ({ slug, ...payload }) => {
    const body = slug ? { slug, ...payload } : payload
    const { data } = await publicApi.post('/public/register/', body)
    return data
  },
```

(Si `register` usaba `toFormData`, mantener el mismo transporte; solo hacer `slug` opcional.)

- [ ] **Step 2: `GymPublicRegisterPage.jsx` — resolver por subdominio (sin slug)**

- Quitar `useParams` y la variable `slug`.
- `useEffect`: llamar `registrationApi.validateInvite()` (sin argumentos); en `catch` → `STATUS.INVALID`. Quitar el guard `if (!slug)`. El array de dependencias pasa a `[]`.
- `onSubmit`: `await registrationApi.register({ ...form })` (sin `slug`).

- [ ] **Step 3: Crear `frontend/src/pages/TrialLinkRedirect.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { registrationApi } from '../api/client'

// Back-compat: links viejos /{slug}/clase-gratis (apex) -> redirige al subdominio de la org.
export default function TrialLinkRedirect() {
  const { slug } = useParams()
  const [invalid, setInvalid] = useState(false)

  useEffect(() => {
    let active = true
    const go = async () => {
      try {
        const data = await registrationApi.validateInvite({ slug })
        if (data?.public_registration_url) {
          window.location.replace(data.public_registration_url)
        } else if (active) {
          setInvalid(true)
        }
      } catch {
        if (active) setInvalid(true)
      }
    }
    go()
    return () => { active = false }
  }, [slug])

  if (invalid) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-black p-4 text-center">
        <div className="w-full max-w-md rounded-3xl border border-brand-line bg-brand-soft/95 p-8">
          <h1 className="font-display text-2xl font-bold">Link inválido o expirado</h1>
          <p className="mt-3 text-sm text-brand-muted">Pídele al gimnasio el link actualizado.</p>
          <Link to="/login" className="mt-6 inline-flex min-h-11 items-center rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white">
            Ir a iniciar sesión
          </Link>
        </div>
      </div>
    )
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-black text-brand-muted">
      Redirigiéndote al gimnasio…
    </div>
  )
}
```

- [ ] **Step 4: `App.jsx` — rutas**

Agregar el import y reemplazar la ruta pública `/:slug/clase-gratis` por dos rutas:

```jsx
import TrialLinkRedirect from './pages/TrialLinkRedirect'
```

```jsx
      <Route path="/clase-gratis" element={<GymPublicRegisterPage />} />
      <Route path="/:slug/clase-gratis" element={<TrialLinkRedirect />} />
```

- [ ] **Step 5: Verificar build**

Run: `cd frontend && npm run build`
Expected: build OK, sin errores de import.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.jsx frontend/src/pages/GymPublicRegisterPage.jsx frontend/src/pages/TrialLinkRedirect.jsx frontend/src/api/client.js
git commit -m "feat(frontend): /clase-gratis por subdominio + redirect de links viejos"
```

---

### Task 7: Verificación integral

**Files:** ninguno (solo corridas).

- [ ] **Step 1: Suite backend completa**

Run: `cd backend && python -m pytest -q`
Expected: verde (todos, sin regresiones; incluye los tests nuevos).

- [ ] **Step 2: (Si es tratable) E2E de API del flujo trial por subdominio**

Run: `cd backend && python -m pytest tests/e2e/test_feature2_trial_and_email.py -q` (o el harness E2E correspondiente).
Expected: verde o, si el harness no levanta en el entorno, documentarlo y omitir (no es bloqueante).

- [ ] **Step 3: Resumen de verificación al usuario**

Reportar: resultado de pytest (número de tests), archivos tocados, y que **no** se hizo push (rama `fix/trial-link-subdomain` local, pendiente de validación).

---

## Self-Review

- **Cobertura del spec:** Helper (Task 1), duplicados serializer+comando (Tasks 2-3), resolución por subdominio (Task 4), verify+reset (Task 5), frontend ruta+redirect (Task 6), tests de valor de URL (Tasks 1-3, 5), verificación pytest (Task 7). ✔
- **Placeholders:** ninguno; todo el código y comandos están completos. ✔
- **Consistencia de tipos/nombres:** `organization_public_base_url` y `trial_signup_url` se usan con la misma firma en serializers, comando y views; `_resolve_public_org(request, slug)` idéntico en invite/register. ✔
- **Riesgo conocido:** los tests que overridean settings a shape prod deben usar `HTTP_HOST` coherente con `BASE_DOMAIN` (`org-1.tymroapp.com`), si no el middleware no resuelve el subdominio. Ya reflejado en Tasks 4-5. ✔
