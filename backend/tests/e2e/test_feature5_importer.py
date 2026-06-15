"""E2E Feature 5 — Importador de datos (ciclo validate -> commit).

Camino real por HTTP contra el server vivo: un gym_admin sube un .xlsx de
Disciplinas, valida (obtiene token atado al sha256 del archivo) y commitea con los
MISMOS bytes. Luego confirma por la API que las disciplinas quedaron creadas.
"""
from io import BytesIO

import pytest

from core.models import Discipline
from .conftest import auth
from . import factories as f  # noqa: F401  (mantiene consistencia de imports)

pytestmark = pytest.mark.django_db(transaction=True)

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
HEADERS = ['Nombre', 'Descripción', 'Activa']


def _xlsx_bytes(rows, headers=HEADERS):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = 'Datos'
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _file_part(file_bytes, name='disciplinas.xlsx'):
    return {'name': name, 'mimeType': XLSX_MIME, 'buffer': file_bytes}


def test_import_disciplines_validate_then_commit(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Import')
    make_user('imp_admin', organization=org, role='gym_admin')
    token_auth = auth(login('imp_admin'))

    file_bytes = _xlsx_bytes([['Yoga', 'Clase de yoga', 'Sí'],
                              ['Crossfit', '', 'No']])

    # 1) Validar.
    validate = api.post(
        '/api/imports/disciplines/validate/',
        multipart={'file': _file_part(file_bytes)},
        headers=token_auth,
    )
    assert validate.status == 200, validate.text()
    vbody = validate.json()
    assert vbody['can_commit'] is True, vbody
    import_token = vbody['token']
    assert import_token

    # 2) Commitear con los MISMOS bytes + token.
    commit = api.post(
        '/api/imports/disciplines/commit/',
        multipart={'file': _file_part(file_bytes), 'token': import_token},
        headers=token_auth,
    )
    assert commit.status == 201, commit.text()
    assert commit.json()['created'] == 2, commit.text()

    # 3) Confirmar por la API que las disciplinas existen y están scoping a la org.
    listing = api.get('/api/disciplines/', headers=token_auth)
    assert listing.status == 200, listing.text()
    rows = listing.json()
    rows = rows if isinstance(rows, list) else rows.get('results', [])
    names = {r['name'] for r in rows}
    assert {'Yoga', 'Crossfit'} <= names, names

    # Y que efectivamente quedaron en la organización correcta (sin fuga cross-tenant).
    assert Discipline.objects.filter(organization=org, name='Yoga').exists()
    assert Discipline.objects.filter(organization=org).count() == 2


def test_import_forbidden_for_student(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Import2')
    make_user('imp_alu', organization=org, role='student')
    file_bytes = _xlsx_bytes([['Yoga', '', 'Sí']])

    resp = api.post(
        '/api/imports/disciplines/validate/',
        multipart={'file': _file_part(file_bytes)},
        headers=auth(login('imp_alu')),
    )
    assert resp.status == 403, resp.text()
