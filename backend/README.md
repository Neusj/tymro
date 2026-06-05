# TYMRO Backend

## Setup

```bash
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

## Main endpoints
- `/api/health/`
- `/api/dashboard/`
- `/api/organizations/`
- `/api/branches/`
- `/api/people/`
- `/api/classes/`
- `/api/plans/`
- `/api/teacher-payment-rules/`

This base uses SQLite for zero-config local startup, but `psycopg2-binary` is already included so you can move to PostgreSQL next.
