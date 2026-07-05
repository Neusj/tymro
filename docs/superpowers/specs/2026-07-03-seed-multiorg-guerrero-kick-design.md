# Seed multi-org (guerrero/kick) + config de login por subdominio

Fecha: 2026-07-03

## Contexto y decisión de arquitectura

El usuario dudaba si el modelo de identidad estaba "mal". Tras aclararlo, el
modelo actual (**Modelo A**) es exactamente el deseado y **no requiere refactor**:

- Una persona en dos gyms = **dos filas `CustomUser` independientes** (rol propio,
  password propio, perfil propio) que solo comparten el string del email.
- Lo permite el constraint `uniq_email_per_org` (`accounts/models.py`): email único
  *por organización*, repetible entre orgs.
- El login se desambigua por **subdominio** (`OrganizationMiddleware` +
  `LoginView`): en `<gym>.<BASE_DOMAIN>` solo entran usuarios de esa org; en el
  apex / labels reservados solo cuentas de plataforma (superadmin).

Decisiones confirmadas:
- **Superadmin** = usuario global de plataforma (org NULL). Correcto tal cual está.
- **Una sola base de datos** (shared DB, aislamiento por `organization_id`). Es lo
  correcto para los requisitos (superadmin ve todo + persona multi-org). DB-por-tenant
  los complicaría. No se cambia.
- La BBDD de QA es **descartable**: se puede borrar y reseed.

## Esquema de subdominios (clave)

- `BASE_DOMAIN=tymroapp.com` (QA/prod). En local: `BASE_DOMAIN=localhost`.
- Gyms como subdominio de **1 nivel**: `guerrero.tymroapp.com`, `kick.tymroapp.com`,
  `r2b.tymroapp.com`. Cubiertos por el **Universal SSL gratis** (`*.tymroapp.com`).
- `qa` está en `RESERVED_SUBDOMAINS` → `qa.tymroapp.com` resuelve a **contexto
  plataforma** (superadmin), no a un tenant. Por eso el host de QA no se rompe.
- **NO** se usa el esquema de 2 niveles (`guerrero.qa.tymroapp.com`), que exigiría
  Advanced Certificate Manager (de pago). Este era el bloqueante "cert TLS 2 niveles"
  anotado; con 1 nivel desaparece.
- El seed guarda solo la **etiqueta** de subdominio; el host completo lo arma
  `BASE_DOMAIN`. Así el mismo seed sirve para local/QA/prod cambiando solo `.env`.

Riesgo externo (no resoluble por código): el túnel de Cloudflare es token-managed;
su ingress vive en el dashboard. Para que `*.tymroapp.com` llegue al backend hace
falta DNS wildcard + ingress wildcard del túnel. El usuario cree que ya está.

## Alcance de la implementación (3 piezas, sin tocar auth)

### 1. Extender el seed (`seed_demo_data.py`) — Opción "sumar sin romper"
- Se mantienen intactos los datos que la suite E2E espera (`r2b-qa`, `gym-test`,
  `e2e-gym`, `r2b`, `tymro-demo`; usuarios `student1`/`gymadmin`/`teacher1`;
  `juan@demo.local`). No se rompen los ~335 tests.
- Se agregan dos orgs demo a `ALL_SLUGS` + `ORG_DEFAULTS`:
  - `guerrero` → "Guerrero Fight Club" (subdominio `guerrero`)
  - `kick` → "Kick BJJ Academy" (subdominio `kick`)
  - No canónicas → sus usuarios de infra llevan sufijo (`gymadmin_guerrero`, etc.).
- La persona multi-org, como **dos usuarios independientes** (mismo email
  `user1@correo.com`, distinta org, distinto rol):

  | Email | Org | Rol | Username interno | Password |
  |---|---|---|---|---|
  | user1@correo.com | guerrero | Profesor | user1_guerrero | teacher123 |
  | user1@correo.com | kick | Alumno (BJJ) | user1_kick | student123 |

  Password distinto a propósito: refuerza que son cuentas separadas. El alumno de
  kick queda con un plan para poder reservar/asistir.

### 2. Config `.env` que enciende el login multi-org
Hoy `BASE_DOMAIN` cae en `localhost` (default) y `ALLOWED_HOSTS` no tiene wildcard,
así que la resolución por subdominio está de facto apagada. Cambios:
- Agregar `BASE_DOMAIN` (valor según entorno de prueba).
- `ALLOWED_HOSTS`: agregar wildcard del dominio base (`.tymroapp.com`; en local `.localhost`).
- `CSRF_TRUSTED_ORIGINS`: agregar `https://*.tymroapp.com`.

### 3. Borrar y reseed
1. `flush --no-input` (borra data, mantiene esquema/migraciones)
2. `migrate`
3. `seed_demo_data --org=all`

Verificación: entrar a `guerrero.<host>` con user1@correo.com → Profesor; a
`kick.<host>` con user1@correo.com → Alumno. Confirmar que son dos usuarios distintos.

## Fuera de alcance
- No hay refactor del modelo de identidad (Modelo A ya es lo deseado).
- No se toca `OrganizationMiddleware`, `LoginView` ni permisos.
- El cert/ingress de Cloudflare es infra externa (dashboard), no código.
