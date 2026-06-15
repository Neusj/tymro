"""E2E Feature 1 — Pago a profesor 'per_plan_price'.

Valida end-to-end que, tras completarse una clase, el PROFESOR VE por la API el
monto correcto: % del 'precio por clase' (final_price / total_classes) de los
planes de sus alumnos. Se ejerce el camino real de producción:
  1. admin lista clases  -> el server auto-completa la clase pasada y dispara el
     cálculo de pago (_sync_class_statuses -> calculate_teacher_payment).
  2. profesor consulta /api/teacher-payments/my/ y ve el record con el monto.
"""
from datetime import timedelta

import pytest

from core.models import GymClass, TeacherPaymentRule
from .conftest import auth
from . import factories as f

pytestmark = pytest.mark.django_db(transaction=True)

PPP = TeacherPaymentRule.PaymentType.PER_PLAN_PRICE
ACTIVE = TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS


def test_teacher_sees_correct_per_plan_price_payment(api, login, make_organization, make_user):
    org = make_organization('Gimnasio PPP')
    admin = make_user('ppp_admin', organization=org, role='gym_admin')  # noqa: F841
    teacher = make_user('ppp_teach', organization=org, role='teacher', first_name='Ana')
    s1 = make_user('ppp_s1', organization=org, role='student')
    s2 = make_user('ppp_s2', organization=org, role='student')
    branch = f.make_branch(org)

    # Clase ya terminada (end en el pasado) pero aún marcada SCHEDULED:
    # el listado del admin la auto-completará.
    start = f.now() - timedelta(hours=2)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, name='Clase PPP',
    )

    # s1: plan 15000/4 = 3750 por clase ; s2: plan 4000/24 = 166.6667 por clase.
    sp1 = f.give_student_plan(s1, f.make_plan(org, 4, 15000), 4, 15000)
    sp2 = f.give_student_plan(s2, f.make_plan(org, 24, 4000), 24, 4000)
    for student, sp in ((s1, sp1), (s2, sp2)):
        f.enroll(gym_class, student)
        f.consume(student, sp, gym_class)

    f.make_rule(org, PPP, amount=20, teacher=teacher, per_plan_price_base=ACTIVE)

    # 1) El admin lista clases -> dispara auto-complete + cálculo de pago.
    admin_token = login('ppp_admin')
    listed = api.get('/api/classes/', headers=auth(admin_token))
    assert listed.status == 200, listed.text()
    rows = listed.json()
    rows = rows if isinstance(rows, list) else rows.get('results', [])
    this_class = next(r for r in rows if r['id'] == gym_class.id)
    assert this_class['status'] == GymClass.Status.COMPLETED, this_class

    # 2) El profesor ve su pago calculado por la API real.
    teacher_token = login('ppp_teach')
    resp = api.get('/api/teacher-payments/my/', headers=auth(teacher_token))
    assert resp.status == 200, resp.text()
    records = resp.json()
    assert len(records) == 1, records
    record = records[0]
    # (3750 + 166.6667) * 0.20 = 783.33
    assert record['total_students'] == 2
    assert float(record['total_amount']) == 783.33


def test_unlimited_plan_excluded_from_teacher_payment(api, login, make_organization, make_user):
    org = make_organization('Gimnasio PPP2')
    make_user('ppp2_admin', organization=org, role='gym_admin')
    teacher = make_user('ppp2_teach', organization=org, role='teacher')
    s1 = make_user('ppp2_s1', organization=org, role='student')
    s2 = make_user('ppp2_s2', organization=org, role='student')
    branch = f.make_branch(org)

    start = f.now() - timedelta(hours=2)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, name='Clase PPP2',
    )
    sp1 = f.give_student_plan(s1, f.make_plan(org, 4, 15000), 4, 15000)            # limitado
    sp2 = f.give_student_plan(s2, f.make_plan(org, 0, 60000, unlimited=True), 0, 60000, unlimited=True)
    for student, sp in ((s1, sp1), (s2, sp2)):
        f.enroll(gym_class, student)
        f.consume(student, sp, gym_class)

    f.make_rule(org, PPP, amount=20, teacher=teacher, per_plan_price_base=ACTIVE)

    api.get('/api/classes/', headers=auth(login('ppp2_admin')))

    resp = api.get('/api/teacher-payments/my/', headers=auth(login('ppp2_teach')))
    assert resp.status == 200, resp.text()
    record = resp.json()[0]
    assert record['total_students'] == 2           # ambos inscritos
    assert float(record['total_amount']) == 750.0  # solo el limitado aporta: 3750 * 0.20
