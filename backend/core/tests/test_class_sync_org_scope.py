"""`_sync_class_statuses` no puede escribir en clases de OTRA organización.

Es una función de ESCRITURA disfrazada de listado: `refresh_status_from_schedule(save=True)`
persiste `status`/`is_active`/`closed_at`, `consolidate_attendance` inserta filas de
`Attendance` y, al completar, `calculate_teacher_payment` crea el `TeacherPaymentRecord`
del profe.

Dos llamadores la invocaban SIN filtrar por organización:

    core/views.py  dashboard_summary            -> _sync_class_statuses()            # todas
    core/views.py  EnrollmentViewSet.get_queryset -> _sync_class_statuses(GymClass.objects.all())

Cualquier autenticado —incluido un alumno— disparaba así el cierre de clases, la
consolidación de asistencias y la creación de pagos a profesores de TODAS las
organizaciones. No es una fuga de lectura (el scoping del listado se aplica después),
pero sí una escritura cross-org, y el momento en que se materializan los pagos de otro
gimnasio queda en manos de un tercero (regla #1: scoping ANTES de cualquier escritura).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Attendance, Branch, Enrollment, GymClass

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _stale_class(org, teacher, student):
    """Clase de `org` que YA terminó pero sigue en SCHEDULED: el próximo sync la cerrará."""
    branch = Branch.objects.create(organization=org, name=f'Sede {org.slug}')
    start = timezone.now() - timedelta(hours=3)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase vencida',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return gym_class


@pytest.fixture
def two_orgs(make_organization, make_user):
    org_a = make_organization()
    org_b = make_organization()
    victim_teacher = make_user('teach_b', organization=org_b, role='teacher')
    victim_student = make_user('alu_b', organization=org_b, role='student', email='alu_b@b.cl')
    return {
        'org_a': org_a,
        'org_b': org_b,
        'victim_class': _stale_class(org_b, victim_teacher, victim_student),
        'victim_student': victim_student,
        'intruder_student': make_user('alu_a', organization=org_a, role='student', email='alu_a@a.cl'),
        'intruder_admin': make_user('admin_a', organization=org_a, role='gym_admin'),
    }


def _assert_untouched(two_orgs):
    victim = two_orgs['victim_class']
    victim.refresh_from_db()
    assert victim.status == GymClass.Status.SCHEDULED, (
        'una request de otra organización cerró esta clase'
    )
    assert victim.closed_at is None
    assert not Attendance.objects.filter(gym_class=victim).exists(), (
        'una request de otra organización consolidó estas asistencias'
    )


def test_enrollments_list_does_not_sync_other_orgs(api_client, two_orgs):
    """`GET /api/enrollments/` de un alumno de la org A no puede cerrar clases de la org B."""
    _login(api_client, two_orgs['intruder_student'])

    resp = api_client.get('/api/enrollments/')

    assert resp.status_code == 200, resp.content
    _assert_untouched(two_orgs)


def test_my_reservations_does_not_sync_other_orgs(api_client, two_orgs):
    """Mismo camino por la acción `my`, que es la que usa la app del alumno."""
    _login(api_client, two_orgs['intruder_student'])

    resp = api_client.get('/api/enrollments/my/')

    assert resp.status_code == 200, resp.content
    _assert_untouched(two_orgs)


def test_dashboard_does_not_sync_other_orgs(api_client, two_orgs):
    """`GET /api/dashboard/` llamaba a `_sync_class_statuses()` sin argumentos."""
    _login(api_client, two_orgs['intruder_admin'])

    resp = api_client.get('/api/dashboard/')

    assert resp.status_code == 200, resp.content
    _assert_untouched(two_orgs)


def test_own_org_is_still_synced_by_the_enrollments_list(api_client, two_orgs, make_user):
    """Regresión: el scoping no puede apagar el sync de la PROPIA organización."""
    teacher_a = make_user('teach_a', organization=two_orgs['org_a'], role='teacher')
    own = _stale_class(two_orgs['org_a'], teacher_a, two_orgs['intruder_student'])
    _login(api_client, two_orgs['intruder_admin'])

    resp = api_client.get('/api/enrollments/')

    assert resp.status_code == 200, resp.content
    own.refresh_from_db()
    assert own.status == GymClass.Status.COMPLETED, 'la propia org sí debe sincronizarse'


def test_own_org_is_still_synced_by_the_dashboard(api_client, two_orgs, make_user):
    """Regresión del mismo scoping por el camino del dashboard."""
    teacher_a = make_user('teach_a2', organization=two_orgs['org_a'], role='teacher')
    own = _stale_class(two_orgs['org_a'], teacher_a, two_orgs['intruder_student'])
    _login(api_client, two_orgs['intruder_admin'])

    resp = api_client.get('/api/dashboard/')

    assert resp.status_code == 200, resp.content
    own.refresh_from_db()
    assert own.status == GymClass.Status.COMPLETED


def test_superadmin_dashboard_still_syncs_everything(api_client, two_orgs, make_user):
    """El superadmin es rol de plataforma: su sync sí abarca todas las organizaciones."""
    make_user('root', organization=None, role='superadmin', email='root@tymro.cl')
    from django.contrib.auth import get_user_model
    root = get_user_model().objects.get(username='root')
    token = api_client.post(
        '/api/login/', {'email': root.email, 'password': PASSWORD}, format='json',
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')

    resp = api_client.get('/api/dashboard/')

    assert resp.status_code == 200, resp.content
    victim = two_orgs['victim_class']
    victim.refresh_from_db()
    assert victim.status == GymClass.Status.COMPLETED
