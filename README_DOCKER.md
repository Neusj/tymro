# TYMRO con Docker y Cloudflare Tunnel

Esta configuracion levanta el stack local con Docker y expone el frontend por Cloudflare Tunnel en `https://tymroapp.com`. El backend Django se conecta a PostgreSQL externo cuando configuras `DATABASE_URL` o las variables `POSTGRES_*`; si no hay configuracion PostgreSQL, usa SQLite como fallback local. El frontend Nginx sirve la SPA y proxya `/api/` y `/media/` al backend Django.

## 1. Crear el tunnel en Cloudflare

1. Entra a Cloudflare Zero Trust.
2. Ve a `Networks` > `Tunnels`.
3. Crea un tunnel nuevo de tipo `Cloudflared`.
4. En `Public Hostname`, configura:
   - Hostname: `tymroapp.com`
   - Service type: `HTTP`
   - URL: `http://frontend:80`
5. Copia el token del tunnel.

## 2. Configurar variables

Copia `.env.example` a `.env` en la raiz del proyecto y completa:

```env
CLOUDFLARE_TUNNEL_TOKEN=tu-token-de-cloudflare
PUBLIC_DOMAIN=tymroapp.com
VITE_API_URL=/api

# Opcion recomendada para BBDD externa:
DATABASE_URL=postgres://usuario:password@host:5432/nombre_db

# Alternativa equivalente:
POSTGRES_DB=nombre_db
POSTGRES_USER=usuario
POSTGRES_PASSWORD=password
POSTGRES_HOST=host
POSTGRES_PORT=5432
```

Para Docker se recomienda dejar `VITE_API_URL=/api`, porque Nginx enruta las llamadas API al backend. Si necesitas compilar apuntando explicitamente al dominio publico, usa `VITE_API_URL=https://tymroapp.com/api`.

No agregues un servicio PostgreSQL al `docker-compose.yml` para este flujo: el contenedor `backend` se conecta al host externo indicado. Al iniciar, ejecuta `python manage.py migrate` contra esa base.

## 3. Levantar el stack

```bash
docker compose up --build
```

URLs locales:

- Frontend: `http://localhost:5173`
- Backend directo: `http://localhost:8000/api/health/`
- Backend via frontend/Nginx: `http://localhost:5173/api/health/`
- Publico por tunnel: `https://tymroapp.com`

Si la base Docker esta vacia, puedes cargar usuarios demo:

```bash
docker compose exec backend python manage.py seed_demo_data
```

Usuarios demo:

- `gymadmin` / `gymadmin123`
- `student1` / `student123`
- `teacher1` / `teacher123`
- `superadmin` / `superadmin123`

## 4. Probar desde celular

1. Levanta el stack con `docker compose up --build`.
2. Confirma que `cloudflared` este conectado en los logs.
3. Abre `https://tymroapp.com` desde el celular.
4. Inicia sesion como `gymadmin`.
5. Ve a `QR asistencia` y genera/inicia la pantalla de recepcion.
6. Escanea el QR desde el celular.
7. Inicia sesion como alumno si la ruta protegida lo solicita.
8. Marca asistencia y verifica el registro en la app.

## 5. Flujo local sin Docker

El flujo local existente se mantiene:

```bash
cd backend
python manage.py migrate
python manage.py runserver
```

```bash
cd frontend
npm install
npm run dev
```

En desarrollo Vite proxya `/api` y `/media` a `http://127.0.0.1:8000`, por lo que puedes usar `VITE_API_URL=/api`.
