# Migración transporte de email Gmail SMTP → Resend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cambiar el transporte de correo de Django de SMTP (Gmail, bloqueado en Railway) a Resend vía su API HTTPS, sin tocar la lógica de envío, los links ni las plantillas.

**Architecture:** Se usa `django-anymail[resend]` como `EMAIL_BACKEND` drop-in: los `send_mail()` existentes salen por `api.resend.com` (HTTPS 443) sin cambios. En los dos endpoints públicos que hoy hacen hard-500 si el envío falla (reset de contraseña y verify-email), se envuelve el envío en `try/except` + log, devolviendo el mismo éxito. Se eliminan las settings de Gmail SMTP.

**Tech Stack:** Django 5.0.6, DRF 3.15.1, Python 3.13, `django-anymail[resend]`, pytest.

## Global Constraints

- **NO cambiar** la lógica de `send_mail`, ni los cuerpos/asuntos, ni los links de los correos. Solo el transporte y el manejo de error.
- **Paquete:** `django-anymail[resend]` (NO el SDK `resend` oficial). `anymail` NO se agrega a `INSTALLED_APPS` (no hace falta para usar solo el backend).
- **Remitente:** siempre desde `settings.DEFAULT_FROM_EMAIL`; default `no-reply@tymroapp.com`.
- **Única env var nueva:** `RESEND_API_KEY`.
- `settings_test` permanece **intacto** (usa `locmem`); no tocar los tests existentes.
- En `try/except`, mantener `fail_silently=False` para que el error suba y se loguee con `logger.exception(...)`.
- Entorno Windows: el intérprete del venv es `backend/.venv/Scripts/python.exe`; los tests se corren desde `backend/`.
- Rama de trabajo: `fix/email-resend-transport` (ya creada; el spec ya está commiteado ahí).

---

### Task 1: Dependencia Resend + swap de transporte en settings

Instala `django-anymail[resend]`, cambia el `EMAIL_BACKEND` de prod a Resend, agrega `ANYMAIL`, y elimina las settings de Gmail SMTP. Deja un test-guard de que el backend es importable y `ANYMAIL` está configurado.

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/tymro/settings.py:262-274`
- Create: `backend/core/tests/test_email_transport.py`

**Interfaces:**
- Produces: `settings.ANYMAIL['RESEND_API_KEY']` (str, vacío si no hay env var); `EMAIL_BACKEND` = `anymail.backends.resend.EmailBackend` en prod (default cuando `DEBUG=False` y no hay override); `settings.DEFAULT_FROM_EMAIL` (str, default `no-reply@tymroapp.com`).

- [ ] **Step 1: Instalar el paquete en el venv y fijar la versión exacta**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pip install "django-anymail[resend]" && \
  ".venv/Scripts/python.exe" -m pip show django-anymail | grep -i '^Version:'
```
Expected: instala sin error e imprime algo como `Version: 13.0.1`. Anota esa versión para el paso 2.

- [ ] **Step 2: Agregar la dependencia pineada a requirements.txt**

Editar `backend/requirements.txt` — agregar al final (usa la versión exacta que imprimió el paso 1; ejemplo con `13.0.1`):

```
django-anymail[resend]==13.0.1
```

- [ ] **Step 3: Verificar que el backend de Resend es importable**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -c "from anymail.backends.resend import EmailBackend; print('OK', EmailBackend)"
```
Expected: `OK <class 'anymail.backends.resend.EmailBackend'>`

- [ ] **Step 4: Swap del transporte en settings.py**

En `backend/tymro/settings.py`, reemplazar el bloque actual (líneas ~262-274):

```python
# Email — consola en dev, SMTP por env en prod.
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
    if DEBUG
    else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', True)
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@tymroapp.com')
```

por:

```python
# Email — consola en dev, Resend (API HTTPS) en prod. Railway bloquea SMTP saliente (587/465).
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
    if DEBUG
    else 'anymail.backends.resend.EmailBackend',
)
ANYMAIL = {'RESEND_API_KEY': os.getenv('RESEND_API_KEY', '')}
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@tymroapp.com')
```

Nota: NO tocar `_env_bool` (se sigue usando en `SECURE_SSL_REDIRECT`). Solo se elimina la línea `EMAIL_USE_TLS` y las cuatro `EMAIL_HOST*`/`EMAIL_PORT`.

- [ ] **Step 5: Escribir el test-guard de wiring**

Crear `backend/core/tests/test_email_transport.py`:

```python
"""Guardas del transporte de correo (Resend vía django-anymail).

No verifican envío real (settings_test usa locmem); verifican que la dependencia
esté instalada y que la config de Anymail/remitente exista y no arrastre Gmail.
"""
from django.conf import settings


def test_resend_backend_is_importable():
    from anymail.backends.resend import EmailBackend

    assert EmailBackend is not None


def test_anymail_configured_with_resend_key():
    assert 'RESEND_API_KEY' in settings.ANYMAIL


def test_default_from_is_not_gmail():
    assert settings.DEFAULT_FROM_EMAIL
    assert 'gmail' not in settings.DEFAULT_FROM_EMAIL.lower()
```

- [ ] **Step 6: Correr el test-guard**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_email_transport.py -v
```
Expected: 3 passed.

- [ ] **Step 7: Correr la suite completa (verifica que nada se rompió)**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest -q
```
Expected: toda la suite en verde (los tests de correo existentes siguen con `locmem` por `settings_test`).

- [ ] **Step 8: Commit**

```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO" && \
  git add backend/requirements.txt backend/tymro/settings.py backend/core/tests/test_email_transport.py && \
  git commit -m "feat(email): usar Resend (django-anymail) como EMAIL_BACKEND en prod; quitar SMTP Gmail

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: try/except en reset de contraseña (200 aunque falle el envío)

Envuelve el `send_mail` del reset en `try/except` + `logger.exception`, para que un fallo del proveedor no rompa la respuesta y se preserve la anti-enumeración (siempre 200).

**Files:**
- Modify: `backend/core/views.py:2` (import), `backend/core/views.py:520` (logger), `backend/core/views.py:546-561` (try/except)
- Test: `backend/core/tests/test_auth.py`

**Interfaces:**
- Consumes: `settings.DEFAULT_FROM_EMAIL` (Task 1).
- Produces: módulo-level `logger = logging.getLogger(__name__)` en `core/views.py` (reutilizado por Task 3).

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `backend/core/tests/test_auth.py`:

```python
def test_reset_request_returns_200_even_if_email_send_fails(api_client, user, monkeypatch):
    # Simula caída del proveedor de correo: el envío lanza.
    def _boom(*args, **kwargs):
        raise RuntimeError('email provider down')

    monkeypatch.setattr('core.views.send_mail', _boom)

    resp = api_client.post(RESET_URL, {'email': 'alice@example.com'}, format='json')

    # Anti-enumeración: responde 200 igual, sin propagar el 500.
    assert resp.status_code == 200
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_auth.py::test_reset_request_returns_200_even_if_email_send_fails -v
```
Expected: FAIL — la excepción `RuntimeError` sube y produce 500 (o error), no 200.

- [ ] **Step 3: Agregar el import de logging**

En `backend/core/views.py`, reemplazar la línea 2:

```python
import csv
```
por:
```python
import csv
import logging
```

- [ ] **Step 4: Agregar el logger a nivel de módulo**

En `backend/core/views.py`, justo antes de `class PasswordResetRequestView(APIView):` (línea ~521), agregar una línea a nivel de módulo:

```python
logger = logging.getLogger(__name__)


class PasswordResetRequestView(APIView):
```

- [ ] **Step 5: Envolver el send_mail del reset en try/except**

En `backend/core/views.py`, reemplazar el bloque de envío del reset (líneas ~551-561):

```python
            send_mail(
                subject='Restablecer tu contraseña — TYMRO',
                message=(
                    'Recibimos una solicitud para restablecer tu contraseña.\n\n'
                    f'Abre este enlace para elegir una nueva contraseña:\n{reset_link}\n\n'
                    'Si no fuiste tú, puedes ignorar este correo.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
```

por:

```python
            try:
                send_mail(
                    subject='Restablecer tu contraseña — TYMRO',
                    message=(
                        'Recibimos una solicitud para restablecer tu contraseña.\n\n'
                        f'Abre este enlace para elegir una nueva contraseña:\n{reset_link}\n\n'
                        'Si no fuiste tú, puedes ignorar este correo.'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception:
                # El envío falló (proveedor caído/mal config): NO lo revelamos al
                # cliente (anti-enumeración). Logueamos para diagnóstico.
                logger.exception('Fallo enviando email de reset de contraseña a %s', email)
```

- [ ] **Step 6: Correr el test para verificar que pasa**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_auth.py::test_reset_request_returns_200_even_if_email_send_fails -v
```
Expected: PASS.

- [ ] **Step 7: Correr todo test_auth.py (no romper reset/login existentes)**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_auth.py -q
```
Expected: todo verde (incluye `test_reset_request_sends_email_only_for_existing_user`, que sigue usando `locmem`).

- [ ] **Step 8: Commit**

```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO" && \
  git add backend/core/views.py backend/core/tests/test_auth.py && \
  git commit -m "fix(auth): reset de contraseña responde 200 aunque falle el envío de email (+log)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: try/except en verify-email (201 aunque falle el envío)

Mismo patrón en el registro público: si el correo de verificación falla, se loguea y se devuelve el `201` igual (el usuario ya quedó creado antes del envío).

**Files:**
- Modify: `backend/core/views.py:696-707` (try/except)
- Test: `backend/core/tests/test_public_registration.py`

**Interfaces:**
- Consumes: `logger` (módulo-level, definido en Task 2); `settings.DEFAULT_FROM_EMAIL` (Task 1).

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `backend/core/tests/test_public_registration.py`:

```python
def test_registration_returns_201_even_if_email_send_fails(api_client, make_organization, monkeypatch):
    org = make_organization(name='Cross Santiago')

    def _boom(*args, **kwargs):
        raise RuntimeError('email provider down')

    monkeypatch.setattr('core.views.send_mail', _boom)

    resp = api_client.post(REGISTER_URL, _register_payload(org), format='json')

    # El envío falló pero el registro debe completarse igual.
    assert resp.status_code == 201

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email__iexact='pros@example.com')
    assert user.organization_id == org.id
    assert user.role == 'student'
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_public_registration.py::test_registration_returns_201_even_if_email_send_fails -v
```
Expected: FAIL — la excepción sube y produce 500, no 201.

- [ ] **Step 3: Envolver el send_mail de verify-email en try/except**

En `backend/core/views.py`, reemplazar el bloque de envío del registro (líneas ~696-707):

```python
        send_mail(
            subject=f'Confirma tu email — {organization.name}',
            message=(
                f'¡Bienvenido/a a {organization.name}!\n\n'
                'Confirma tu email para activar tu cuenta y agendar tu clase de prueba gratis:\n'
                f'{verify_link}\n\n'
                'Si no fuiste tú, puedes ignorar este correo.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
```

por:

```python
        try:
            send_mail(
                subject=f'Confirma tu email — {organization.name}',
                message=(
                    f'¡Bienvenido/a a {organization.name}!\n\n'
                    'Confirma tu email para activar tu cuenta y agendar tu clase de prueba gratis:\n'
                    f'{verify_link}\n\n'
                    'Si no fuiste tú, puedes ignorar este correo.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            # El usuario ya se creó; si el correo de verificación falla, lo logueamos
            # y devolvemos éxito igual (puede reintentar / pedir reenvío).
            logger.exception('Fallo enviando email de verificación a %s', user.email)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_public_registration.py::test_registration_returns_201_even_if_email_send_fails -v
```
Expected: PASS.

- [ ] **Step 5: Correr todo test_public_registration.py (no romper el happy path)**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest core/tests/test_public_registration.py -q
```
Expected: todo verde (incluye `test_public_registration_happy_path`, que usa `locmem` y sigue viendo el correo en `mailoutbox`).

- [ ] **Step 6: Commit**

```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO" && \
  git add backend/core/views.py backend/core/tests/test_public_registration.py && \
  git commit -m "fix(registro): verify-email responde 201 aunque falle el envío de email (+log)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Limpieza de config (.env local + .env.example + docker-compose.yml)

Quita el bloque Gmail SMTP de la config local, del ejemplo y del compose; deja `RESEND_API_KEY` documentado. `.env` es local (gitignored, no se commitea); `.env.example` y `docker-compose.yml` sí se commitean.

**Files:**
- Modify: `.env` (raíz — local, gitignored: NO se commitea)
- Modify: `.env.example:36-43` (raíz — tracked)
- Modify: `docker-compose.yml:24-33` (raíz — tracked)

**Interfaces:**
- Consumes: `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL` (settings de Task 1).

- [ ] **Step 1: Limpiar el .env local**

En `.env` (raíz del repo), eliminar estas líneas (bloque Gmail, ~41-47):

```
# Fuerza el envío real por SMTP aunque DEBUG=True (si lo quitas, sale por consola).
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=<redacted-gmail-user>
EMAIL_HOST_PASSWORD=<redacted-gmail-app-password>
EMAIL_PORT=587
EMAIL_USE_TLS=True
```

y dejar en su lugar (mantener `DEFAULT_FROM_EMAIL`, ajustado a no-reply):

```
# Email: en dev (DEBUG=True) sale por consola. Para probar Resend real en local,
# setear RESEND_API_KEY y EMAIL_BACKEND=anymail.backends.resend.EmailBackend.
# RESEND_API_KEY=
DEFAULT_FROM_EMAIL=no-reply@tymroapp.com
```

- [ ] **Step 2: Actualizar .env.example**

En `.env.example`, reemplazar las líneas 36-43:

```
# Email (reset de contraseña). En dev (DEBUG=True) sale por consola.
# En producción carga credenciales SMTP reales (Gmail/SendGrid/etc.).
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=no-reply@tymroapp.com
```

por:

```
# Email. En dev (DEBUG=True) sale por consola. En producción usa Resend por API
# HTTPS (django-anymail): setear RESEND_API_KEY. El remitente sale de DEFAULT_FROM_EMAIL
# y debe estar en un dominio verificado en Resend.
RESEND_API_KEY=
DEFAULT_FROM_EMAIL=no-reply@tymroapp.com
```

- [ ] **Step 3: Actualizar docker-compose.yml**

En `docker-compose.yml`, reemplazar el bloque de env de correo (líneas ~24-34, dentro de `services.backend.environment`):

```yaml
      # EMAIL_BACKEND lo decide settings.py según DJANGO_DEBUG: consola en dev,
      # smtp en producción (DEBUG=False). NO lo fijes acá: este compose también
      # corre en QA/prod y un default a consola filtraría los tokens de
      # reset/verificación a los logs del contenedor. Configura SMTP vía las
      # variables EMAIL_HOST/USER/PASSWORD de abajo.
      EMAIL_HOST: ${EMAIL_HOST:-}
      EMAIL_PORT: ${EMAIL_PORT:-587}
      EMAIL_HOST_USER: ${EMAIL_HOST_USER:-}
      EMAIL_HOST_PASSWORD: ${EMAIL_HOST_PASSWORD:-}
      EMAIL_USE_TLS: ${EMAIL_USE_TLS:-True}
      DEFAULT_FROM_EMAIL: ${DEFAULT_FROM_EMAIL:-no-reply@tymroapp.com}
```

por:

```yaml
      # EMAIL_BACKEND lo decide settings.py según DJANGO_DEBUG: consola en dev,
      # Resend (API HTTPS) en producción (DEBUG=False). NO lo fijes acá: este
      # compose también corre en QA/prod y un default a consola filtraría los
      # tokens de reset/verificación a los logs del contenedor. Configura Resend
      # vía RESEND_API_KEY.
      RESEND_API_KEY: ${RESEND_API_KEY:-}
      DEFAULT_FROM_EMAIL: ${DEFAULT_FROM_EMAIL:-no-reply@tymroapp.com}
```

- [ ] **Step 4: Verificar que no quedan referencias a Gmail/SMTP en código ni config versionada**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO" && \
  git grep -nE 'EMAIL_HOST|EMAIL_USE_TLS|EMAIL_PORT|smtp\.gmail|backends\.smtp' -- backend .env.example docker-compose.yml || echo "SIN COINCIDENCIAS (OK)"
```
Expected: `SIN COINCIDENCIAS (OK)` (no debe quedar ninguna referencia SMTP/Gmail en archivos versionados).

- [ ] **Step 5: Correr la suite completa**

Run:
```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO/backend" && \
  ".venv/Scripts/python.exe" -m pytest -q
```
Expected: toda la suite en verde.

- [ ] **Step 6: Commit (.env.example + docker-compose.yml; .env es gitignored, NO se commitea)**

```bash
cd "c:/Users/Javier Neus/Documents/apps/inter/TYMRO" && \
  git add .env.example docker-compose.yml && \
  git commit -m "chore(email): quitar config SMTP Gmail del ejemplo y compose; documentar RESEND_API_KEY

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Cierre (fuera de tareas de código)

Antes de que el reset funcione end-to-end para usuarios reales en prod, alguien con acceso a Railway y DNS debe:

1. **Railway env vars:** agregar `RESEND_API_KEY`; cambiar `DEFAULT_FROM_EMAIL=no-reply@tymroapp.com`; eliminar `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` y `EMAIL_BACKEND` (dejar sin setear).
2. **Resend + DNS:** verificar `tymroapp.com` en Resend añadiendo SPF + DKIM (y opcional DMARC) en Cloudflare. Sin dominio verificado, Resend no entrega a destinatarios arbitrarios.
3. **Deploy:** mergear `fix/email-resend-transport` a `deploy/railway-prod` (es un deploy real).
4. **Smoke test en prod:** pedir un reset con un email real y confirmar que llega.

## Self-Review

**Spec coverage:**
- Objetivo #1 (Resend como EMAIL_BACKEND vía anymail) → Task 1. ✓
- Objetivo #2 (`RESEND_API_KEY`, remitente desde `DEFAULT_FROM_EMAIL`) → Task 1 (steps 2,4) + Task 4. ✓
- Objetivo #3 (no tocar send_mail/links/plantillas) → Global Constraints; Tasks 2/3 solo agregan `try/except` alrededor, sin cambiar cuerpo/asunto/links. ✓
- Objetivo #4 (try/except + log + 200) → Task 2 (reset) y Task 3 (verify-email). ✓
- Objetivo #5 (settings_test locmem intacto; test de 200 con envío fallido) → Global Constraints + Task 2 step 1; equivalente verify-email en Task 3 step 1. ✓
- Objetivo #6 (quitar EMAIL_HOST/PORT/TLS/SSL Gmail) → Task 1 step 4 (settings) + Task 4 (.env/.env.example) + Task 4 step 3 (grep de verificación). ✓
- Env vars Railway → sección Cierre. ✓
- Gate DNS/dominio verificado → sección Cierre. ✓

**Placeholder scan:** sin TBD/TODO; el único valor a completar en ejecución es la versión exacta de `django-anymail` (step 1→2 de Task 1, con comando que la imprime) — no es placeholder, es un valor derivado en el momento. ✓

**Type consistency:** `logger = logging.getLogger(__name__)` se define en Task 2 y se reutiliza en Task 3 (mismo nombre `logger`). `settings.ANYMAIL['RESEND_API_KEY']` y `settings.DEFAULT_FROM_EMAIL` coinciden entre Task 1 y el resto. El target de mock `core.views.send_mail` es el mismo en Tasks 2 y 3. ✓
