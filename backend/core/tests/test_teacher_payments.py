"""Resumen agregado de pagos a profesores y modalidades nuevas.

Cubre:
- La agregacion agrupa por profesor y queda scoped por organizacion.
- El profesor salariado (monthly_fixed) aparece aunque no tenga records por clase.
- Cada modalidad nueva calcula bien (por inscrito, por hora, mensual a nivel periodo).
- El filtro de periodo usa la FECHA DE LA CLASE (no calculated_at).
- Un profesor solo ve su propia fila.
- Export CSV / XLSX responden como descarga.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    Enrollment,
    GymClass,
    TeacherPaymentRule,
)
from core.services.teacher_payments import build_teacher_payment_summary, calculate_teacher_payment

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
SUMMARY_URL = '/api/teacher-payments/summary/'
EXPORT_URL = '/api/teacher-payments/summary/export/'


def _login(api_client, username):
    token = api_client.post(
        '/api/login/', {'username': username, 'password': PASSWORD}, format='json'
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _make_completed_class(org, branch, teacher, start=None, hours=1):
    start = start or (timezone.now() - timedelta(hours=2))
    return GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Clase',
        start_datetime=start,
        end_datetime=start + timedelta(hours=hours),
        status=GymClass.Status.COMPLETED,
    )


def _make_rule(org, teacher, payment_type, amount, calculation_base=None):
    rule = TeacherPaymentRule.objects.create(
        organization=org,
        payment_type=payment_type,
        amount=amount,
        calculation_base=calculation_base,
        is_active=True,
    )
    rule.teachers.add(teacher)
    return rule


def _present(gym_class, student):
    return Attendance.objects.create(
        gym_class=gym_class,
        student=student,
        status=Attendance.Status.PRESENT,
    )


@pytest.fixture
def org_setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher', first_name='Ana', last_name='Pérez')
    s1 = make_user('s1', organization=org, role='student')
    s2 = make_user('s2', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'admin': admin, 'teacher': teacher, 's1': s1, 's2': s2, 'branch': branch}


def test_summary_groups_and_scoped_by_org(api_client, org_setup, make_organization, make_user):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    gym_class = _make_completed_class(org, branch, teacher)
    _present(gym_class, org_setup['s1'])
    _present(gym_class, org_setup['s2'])
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_STUDENT, 1000)
    calculate_teacher_payment(gym_class)

    # Otra organizacion con su propio pago, no debe aparecer.
    org2 = make_organization()
    t2 = make_user('t2', organization=org2, role='teacher')
    b2 = Branch.objects.create(organization=org2, name='Sede2')
    c2 = _make_completed_class(org2, b2, t2)
    _present(c2, make_user('s3', organization=org2, role='student'))
    _make_rule(org2, t2, TeacherPaymentRule.PaymentType.PER_STUDENT, 9999)
    calculate_teacher_payment(c2)

    _login(api_client, 'admin')
    data = api_client.get(SUMMARY_URL).json()

    teacher_ids = {row['teacher_id'] for row in data['rows']}
    assert teacher.id in teacher_ids
    assert t2.id not in teacher_ids  # scoped por organizacion

    row = next(r for r in data['rows'] if r['teacher_id'] == teacher.id)
    assert row['classes_count'] == 1
    assert row['attendees_total'] == 2
    assert row['per_class_total'] == 2000
    assert row['total'] == 2000
    assert data['grand_total'] == 2000


def test_salaried_teacher_appears_without_class_records(api_client, org_setup, make_user):
    org = org_setup['org']
    salaried = make_user('sal', organization=org, role='teacher', first_name='Beto', last_name='Soto')
    _make_rule(org, salaried, TeacherPaymentRule.PaymentType.MONTHLY_FIXED, 500000)

    _login(api_client, 'admin')
    data = api_client.get(SUMMARY_URL).json()

    row = next((r for r in data['rows'] if r['teacher_id'] == salaried.id), None)
    assert row is not None  # aparece aunque no tenga records por clase
    assert row['classes_count'] == 0
    assert row['monthly_total'] == 500000
    assert row['total'] == 500000
    assert 'monthly_fixed' in row['modalities']


def test_monthly_fixed_does_not_create_per_class_record(api_client, org_setup):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.MONTHLY_FIXED, 400000)
    gym_class = _make_completed_class(org, branch, teacher)
    record, created = calculate_teacher_payment(gym_class)
    assert record is None and created is False


def test_per_enrolled_calculation(org_setup):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    gym_class = _make_completed_class(org, branch, teacher)
    Enrollment.objects.create(gym_class=gym_class, student=org_setup['s1'], status='active')
    Enrollment.objects.create(gym_class=gym_class, student=org_setup['s2'], status='active')
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_ENROLLED, 2000)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_students == 2
    assert record.total_amount == 4000


def test_per_hour_calculation(org_setup):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    gym_class = _make_completed_class(org, branch, teacher, hours=2)
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_HOUR, 10000)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 20000  # 2 horas x 10000


def test_monthly_fixed_multiplies_by_calendar_months(org_setup):
    org, teacher = org_setup['org'], org_setup['teacher']
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.MONTHLY_FIXED, 300000)

    # Rango de 3 meses calendario -> 3 x monto, sin clases.
    data = build_teacher_payment_summary(org.id, _date(2026, 1, 1), _date(2026, 3, 31))
    row = next(r for r in data['rows'] if r['teacher_id'] == teacher.id)
    assert row['monthly_total'] == 900000


def test_class_date_filter_excludes_out_of_period(api_client, org_setup):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    # Clase del mes pasado (fuera del periodo por defecto = mes actual).
    first_of_month = timezone.now().replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    last_month = first_of_month - timedelta(days=5)
    gym_class = _make_completed_class(org, branch, teacher, start=last_month)
    _present(gym_class, org_setup['s1'])
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_STUDENT, 1000)
    calculate_teacher_payment(gym_class)

    _login(api_client, 'admin')
    data = api_client.get(SUMMARY_URL).json()  # periodo por defecto = mes actual
    assert all(r['teacher_id'] != teacher.id for r in data['rows'])


def test_teacher_sees_only_own_row(api_client, org_setup, make_user):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    other = make_user('other', organization=org, role='teacher')
    gym_class = _make_completed_class(org, branch, teacher)
    _present(gym_class, org_setup['s1'])
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_STUDENT, 1000)
    calculate_teacher_payment(gym_class)
    # El otro profe tambien tiene sueldo, para asegurar que NO se filtra al primero.
    _make_rule(org, other, TeacherPaymentRule.PaymentType.MONTHLY_FIXED, 200000)

    _login(api_client, 'teach')
    data = api_client.get(SUMMARY_URL).json()
    teacher_ids = {r['teacher_id'] for r in data['rows']}
    assert teacher_ids == {teacher.id}
    assert other.id not in teacher_ids


def test_export_csv(api_client, org_setup):
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    gym_class = _make_completed_class(org, branch, teacher)
    _present(gym_class, org_setup['s1'])
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_STUDENT, 1500)
    calculate_teacher_payment(gym_class)

    _login(api_client, 'admin')
    resp = api_client.get(EXPORT_URL, {'fmt': 'csv'})
    assert resp.status_code == 200
    assert 'attachment' in resp['Content-Disposition']
    assert '.csv' in resp['Content-Disposition']
    body = resp.content.decode('utf-8')
    assert 'Ana' in body
    assert 'TOTAL' in body


def test_export_xlsx(api_client, org_setup):
    pytest.importorskip('openpyxl')
    org, branch, teacher = org_setup['org'], org_setup['branch'], org_setup['teacher']
    gym_class = _make_completed_class(org, branch, teacher)
    _present(gym_class, org_setup['s1'])
    _make_rule(org, teacher, TeacherPaymentRule.PaymentType.PER_STUDENT, 1500)
    calculate_teacher_payment(gym_class)

    _login(api_client, 'admin')
    resp = api_client.get(EXPORT_URL, {'fmt': 'xlsx'})
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp['Content-Type']
    assert '.xlsx' in resp['Content-Disposition']


def _date(year, month, day):
    from datetime import date

    return date(year, month, day)
