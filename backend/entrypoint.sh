#!/usr/bin/env sh
set -e

echo "==> Migrando base de datos..."
python manage.py migrate --no-input

echo "==> Recolectando estaticos..."
python manage.py collectstatic --no-input

echo "==> Iniciando gunicorn en 0.0.0.0:${PORT:-8000} (3 workers)..."
exec gunicorn tymro.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 3 \
    --access-logfile - \
    --error-logfile -
