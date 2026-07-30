"""Regresión: al CANCELAR una clase, los alumnos inscritos deben recuperar la
clase consumida de su plan (devolución de saldo) y su inscripción debe quedar
cancelada. Antes, la acción `cancel` solo cambiaba el estado de la clase y el
alumno perdía la clase consumida (bug H2).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'admin': admin, 'teacher': teacher, 'student': student, 'branch': branch}


def _future_class(setup):
    start = timezone.now() + timedelta(days=1)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _enroll_consuming(setup, gym_class):
    """Inscribe al alumno consumiendo 1 clase de su plan (como una reserva real)."""
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=setup['student'], plan=plan, start_date=today, end_date=today + timedelta(days=30),
        organization_id=plan.organization_id,
        total_classes=10, classes_used=1, final_price=30000,
    )
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
    ConsumptionLog.objects.create(user=setup['student'], student_plan=student_plan, class_instance=gym_class)
    return student_plan, enrollment


def test_cancel_class_refunds_enrolled_students(api_client, setup):
    gym_class = _future_class(setup)
    student_plan, enrollment = _enroll_consuming(setup, gym_class)

    _login(api_client, 'teach')  # el profesor dueño cancela su clase
    resp = api_client.post(
        f'/api/classes/{gym_class.id}/cancel/', {'comment': 'No hay quórum'}, format='json',
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == GymClass.Status.CANCELLED

    student_plan.refresh_from_db()
    enrollment.refresh_from_db()
    assert student_plan.classes_used == 0, 'la clase consumida debe devolverse al cancelar'
    assert enrollment.status == 'cancelled'
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()


def test_bulk_close_cancel_refunds_students(api_client, setup):
    gym_class = _future_class(setup)
    student_plan, enrollment = _enroll_consuming(setup, gym_class)

    _login(api_client, 'admin')
    resp = api_client.post(
        '/api/classes/bulk-close/',
        {'class_ids': [gym_class.id], 'action': 'cancel', 'comment': 'Cierre masivo'},
        format='json',
    )
    assert resp.status_code == 200, resp.content
    assert gym_class.id in resp.json()['updated_ids']

    student_plan.refresh_from_db()
    enrollment.refresh_from_db()
    assert student_plan.classes_used == 0
    assert enrollment.status == 'cancelled'
