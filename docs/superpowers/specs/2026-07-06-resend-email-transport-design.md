# Diseño — Migrar transporte de email de Gmail SMTP a Resend (API HTTPS)

**Fecha:** 2026-07-06
**Rama:** `fix/email-resend-transport` (a crear)
**Estado:** aprobado por el usuario (diseño); pendiente implementación.

## Problema

En producción (Railway) el envío de correo por SMTP saliente está **bloqueado**:
timeout en los puertos 587 y 465. El backend actual usa el SMTP de Gmail
(`smtp.gmail.com`), así que **ningún correo sale**. Esto se manifestó como un
HTTP 500 en `POST /api/password-reset/` ([backend/core/views.py:551](../../../backend/core/views.py#L551)):
`send_mail(..., fail_silently=False)` lanza al no poder conectar al SMTP y la
excepción sube sin manejar. Afecta a **todos los roles y todas las orgs**, no solo
r2b (diagnóstico completo: informe del 2026-07-06).

**Resend** envía por su API HTTPS (`api.resend.com`, puerto 443), que Railway sí
permite. Migramos el **transporte** a Resend; la lógica de negocio, los links y las
plantillas de correo no cambian.

## Objetivos

1. Usar Resend como `EMAIL_BACKEND` vía **`django-anymail[resend]`** (API HTTPS, no SMTP).
2. Nueva env var **`RESEND_API_KEY`**. Remitente desde `DEFAULT_FROM_EMAIL`
   (= `no-reply@tymroapp.com` en prod, sobre dominio verificado).
3. **No** cambiar la lógica de `send_mail`, ni los links, ni las plantillas: solo el
   transporte. Reset de contraseña, verify-email y trial links siguen igual.
4. Envolver el envío en `try/except` en los endpoints **públicos** (reset y
   verify-email): si el proveedor falla, loguear el error y responder con el mismo
   éxito (preserva la anti-enumeración del reset).
5. `settings_test` sigue con `locmem` (tests existentes intactos). Agregar test de
   que el reset responde 200 aunque el envío falle (+ equivalente en verify-email).
6. Quitar del código/config toda dependencia de `EMAIL_HOST/PORT/USER/PASSWORD/
   TLS` de Gmail que ya no aplica.

**No-objetivos:** cambiar modelos/migraciones; tocar el cuerpo/asunto/links de los
correos; reintentos/colas de envío; cambiar los otros dos call sites que no tiran
500 (notificación de clase suspendida y comando de trial followups) más allá de que
heredan el nuevo backend automáticamente.

## Decisiones (confirmadas con el usuario)

- **Paquete:** `django-anymail[resend]` (no el SDK `resend` oficial). Anymail es un
  `EMAIL_BACKEND` drop-in: los `send_mail`/`EmailMessage` existentes funcionan sin
  cambios (cumple objetivo #3). Usa `requests` (ya es dependencia) contra la API REST
  de Resend; no requiere el SDK `resend`. El SDK oficial obligaría a reescribir cada
  call site o a escribir un backend custom — descartado.
- **Remitente en prod:** verificar el dominio **`tymroapp.com`** en Resend (registros
  DNS SPF + DKIM en Cloudflare) y usar `DEFAULT_FROM_EMAIL=no-reply@tymroapp.com`.
  `onboarding@resend.dev` NO entrega a destinatarios arbitrarios (solo al email dueño
  de la cuenta Resend), por lo que no sirve para el go-live real.
- **Alcance del `try/except`:** reset **y** verify-email (ambos endpoints públicos que
  hoy hacen hard-500 si el envío falla). Defensa en profundidad.

## Diseño

### Transporte — [backend/tymro/settings.py](../../../backend/tymro/settings.py)

```python
# Email — consola en dev, Resend (API HTTPS) en prod.
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG
    else 'anymail.backends.resend.EmailBackend',
)
ANYMAIL = {'RESEND_API_KEY': os.getenv('RESEND_API_KEY', '')}
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@tymroapp.com')
```

Se **eliminan** de settings.py: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`. `PASSWORD_RESET_TIMEOUT` se mantiene.

`requirements.txt`: agregar `django-anymail[resend]` (pin exacto confirmado al
instalar; compatible con Django 5.0). `anymail` NO se agrega a `INSTALLED_APPS`
(no es obligatorio para usar solo el backend; sus checks del sistema no bloquean).

### Manejo de error — endpoints públicos

Agregar `import logging` + `logger = logging.getLogger(__name__)` a `views.py`.

- **Reset** ([views.py:551](../../../backend/core/views.py#L551)): el `send_mail`
  (dentro de `if user:`) se envuelve en `try/except Exception`; en el `except`,
  `logger.exception('password reset email failed for %s', email)` y se continúa.
  La vista **siempre** devuelve el mismo 200 (`{'detail': 'Si el email existe...'}`),
  con o sin usuario y con o sin fallo de envío → anti-enumeración preservada.
- **Verify-email** ([views.py:696](../../../backend/core/views.py#L696)): mismo patrón.
  El usuario ya se creó (`user.save()` antes del envío); si el correo falla, se loguea
  y se devuelve igual el `201 Created` (`{'detail': 'Cuenta creada...'}`).
- Se mantiene `fail_silently=False` en ambos: así el error real sube y el `except` lo
  **loguea** (con `fail_silently=True` no habría excepción que registrar). El log sale
  a stderr → visible en Railway.

**Sin cambios:** notificación de clase suspendida ([views.py:2128](../../../backend/core/views.py#L2128),
ya `fail_silently=True`) y comando de trial followups
([send_trial_followups.py:118](../../../backend/core/management/commands/send_trial_followups.py#L118),
ya dentro de su propio `try` y es proceso background). Ambos heredan Resend por el
cambio de backend.

### Tests — [backend/core/tests/test_auth.py](../../../backend/core/tests/test_auth.py)

- `settings_test` **intacto** (`locmem`, [backend/tymro/settings_test.py:11](../../../backend/tymro/settings_test.py#L11)).
- Nuevo test (requerido, objetivo #5): con `send_mail` mockeado
  (`unittest.mock.patch('core.views.send_mail', side_effect=Exception('down'))`),
  `POST /api/password-reset/` con email de usuario existente responde **200** y no
  propaga la excepción.
- Nuevo test (por simetría, ya que también protegemos verify-email): con el envío
  mockeado a fallar, el registro público responde **201** igual y el usuario queda
  creado.

### Limpieza de config

- [.env](../../../.env) raíz: quitar el bloque Gmail
  (`EMAIL_BACKEND`/`EMAIL_HOST`/`EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD`/`EMAIL_PORT`/
  `EMAIL_USE_TLS`). Dev cae a **console backend** (DEBUG=True). Dejar
  `DEFAULT_FROM_EMAIL=no-reply@tymroapp.com`. Comentario: para probar Resend real en
  local, setear `RESEND_API_KEY` + `EMAIL_BACKEND=anymail.backends.resend.EmailBackend`.
- [.env.example](../../../.env.example): reemplazar las líneas SMTP (38–42) por
  `RESEND_API_KEY=` y un comentario que explique consola-en-dev / Resend-en-prod.

## Variables de entorno en Railway

**➕ Agregar:** `RESEND_API_KEY` = *(secret del dashboard de Resend)*
**✏️ Cambiar:** `DEFAULT_FROM_EMAIL` = `no-reply@tymroapp.com` *(hoy una cuenta Gmail)*
**➖ Eliminar:** `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS`, y `EMAIL_BACKEND` (dejar sin setear → usa el default = Resend en prod).
**✅ Sin cambios:** `FRONTEND_URL`, `BASE_DOMAIN`, `PUBLIC_DOMAIN`, `SECRET_KEY`, DB,
CORS/CSRF, pagos, etc.

## Prerrequisito NO-código (gate de go-live)

Verificar `tymroapp.com` en Resend añadiendo los registros DNS **SPF + DKIM** (y
opcionalmente DMARC) en **Cloudflare**. Sin dominio verificado, Resend acepta la
llamada pero **no entrega** a usuarios reales. Es tarea de infra/DNS, en paralelo al
código; el envío por HTTPS ya no dará 500, pero la entrega depende de este paso.

## Criterios de aceptación

1. `EMAIL_BACKEND` en prod resuelve a `anymail.backends.resend.EmailBackend`; no queda
   ninguna referencia a SMTP/Gmail en código ni en `.env`/`.env.example`.
2. `POST /api/password-reset/` con email real responde **200** aunque el envío lance
   excepción (test verde), y el error se loguea.
3. Registro público (verify-email) responde **201** aunque el envío falle; usuario creado.
4. Suite `pytest` completa en verde (incluidos los tests nuevos); `settings_test` sin cambios.
5. `RESEND_API_KEY` es la única env var nueva; el remitente sale de `DEFAULT_FROM_EMAIL`.
