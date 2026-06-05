# TYMRO

Base avanzada para arrancar el MVP del SaaS de gimnasios.

## Estructura
- `backend/` Django + DRF
- `front/` React + Vite + Tailwind

## Backend
```bash
cd backend
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

## Front
```bash
cd front
npm install
npm run dev
```

## Qué incluye
- Paleta global aplicada: negro, rojo, blanco, naranja y azul
- Dashboard inicial en React
- API base en Django REST
- Modelos iniciales para:
  - organizaciones
  - sucursales
  - personas (alumnos/profesores/admin)
  - tipos de clase
  - clases
  - reservas / enrollments
  - asistencia
  - planes
  - reglas de pago a profesores
  - registros de pago

## Nota
Para que levante sin fricción local, esta base usa SQLite en desarrollo. Ya viene `psycopg2-binary` instalado para migrar a PostgreSQL en el siguiente paso.
