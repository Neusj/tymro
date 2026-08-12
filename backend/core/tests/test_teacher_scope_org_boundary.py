"""El rol `teacher` tiene que estar acotado por organización, no solo por `teacher_id`.

Todas las puertas del profesor confiaban ÚNICAMENTE en la FK:

    GymClass.objects.filter(teacher_id=user.id)          # get_queryset
    _is_teacher(user) and gym_class.teacher_id == user.id  # _can_close_or_cancel, attendance, ...

Basta con un `teacher_id` "rancio" —una clase de la org A cuyo profesor hoy pertenece a la
org B— para que ese usuario lea y ESCRIBA en la org A. Y el estado es alcanzable:

* `PATCH /api/users/{id}/ {"organization": B}` lo puede hacer el superadmin, y
  `GymClass.teacher` es `SET_NULL`, no CASCADE: las clases viejas de A conservan el
  `teacher_id`.
* La otra puerta —`ClassTemplate` con un profesor de otra org, que generaba clases con
  `teacher_id` ajeno— se cerró en `ClassTemplate.clean()`; este test es la defensa en
  profundidad del lado de la VISTA, que es la que premiaba el estado.

La regla #1 dice `filter(organization_id=request.user.organization_id)`: el scope del
profesor es la intersección de "mis clases" con "mi organización", nunca solo la FK.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Attendance, Branch, Enrollment, GymClass

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
DENIED = {403, 404}


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def stale_teacher(make_organization, make_user):
    """Una clase de la org A cuyo profesor migró a la org B (FK rancia por SET_NULL)."""
    org_a = make_organization()
    org_b = make_organization()
    branch_a = Branch.objects.create(organization=org_a, name='Sede A')
    student_a = make_user('alu_a', organization=org_a, role='student', email='alu_a@a.cl')

    # El profe nace en A, dicta la clase, y después se lo mueven a B.
    teacher = make_user('nomade', organization=org_a, role='teacher', email='nomade@x.cl')
    start = timezone.now() + timedelta(days=2)
    class_a = GymClass.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher, name='Clase de A',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    enrollment_a = Enrollment.objects.create(
        gym_class=class_a, student=student_a, status='active',
    )
    teacher.organization = org_b
    teacher.save(update_fields=['organization'])

    return {
        'org_a': org_a, 'org_b': org_b, 'teacher': teacher,
        'class_a': class_a, 'student_a': student_a, 'enrollment_a': enrollment_a,
    }


def _class_state(stale_teacher):
    stale_teacher['class_a'].refresh_from_db()
    stale_teacher['enrollment_a'].refresh_from_db()
    return (
        stale_teacher['class_a'].status,
        stale_teacher['class_a'].is_active,
        stale_teacher['class_a'].closed_by_id,
        stale_teacher['enrollment_a'].status,
        Attendance.objects.filter(gym_class=stale_teacher['class_a']).count(),
    )


def test_stale_teacher_does_not_see_the_other_orgs_class(api_client, stale_teacher):
    """Lectura: el listado del profe se acota a su organización actual."""
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.get('/api/classes/')

    assert resp.status_code == 200, resp.content
    rows = resp.json()
    rows = rows['results'] if isinstance(rows, dict) else rows
    leaked = [r for r in rows if r['id'] == stale_teacher['class_a'].id]
    assert not leaked, f'la clase de la org A se filtró al profe de la org B: {leaked}'


def test_stale_teacher_cannot_read_the_other_orgs_roster(api_client, stale_teacher):
    """`enrolled-students` devuelve PII del alumno (nombre, email, estado de plan)."""
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.get(f'/api/classes/{stale_teacher["class_a"].id}/enrolled-students/')

    assert resp.status_code in DENIED, resp.content


def test_stale_teacher_cannot_list_enrollable_students_of_another_org(api_client, stale_teacher):
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.get(f'/api/classes/{stale_teacher["class_a"].id}/enrollable-students/')

    assert resp.status_code in DENIED, resp.content


def test_stale_teacher_cannot_write_attendance_in_another_org(api_client, stale_teacher):
    before = _class_state(stale_teacher)
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.post(f'/api/classes/{stale_teacher["class_a"].id}/attendance/', {
        'attendances': [{'student_id': stale_teacher['student_a'].id, 'status': 'present'}],
    }, format='json')

    assert resp.status_code in DENIED, resp.content
    assert _class_state(stale_teacher) == before


def test_stale_teacher_cannot_cancel_another_orgs_class(api_client, stale_teacher):
    """La peor: cancela la clase, cierra las inscripciones y queda como `closed_by`."""
    before = _class_state(stale_teacher)
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.post(f'/api/classes/{stale_teacher["class_a"].id}/cancel/', {
        'comment': 'hack',
    }, format='json')

    assert resp.status_code in DENIED, resp.content
    assert _class_state(stale_teacher) == before


def test_stale_teacher_cannot_complete_early_another_orgs_class(api_client, stale_teacher):
    """`complete-early` además consolida asistencias y crea el pago al profe."""
    before = _class_state(stale_teacher)
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.post(f'/api/classes/{stale_teacher["class_a"].id}/complete-early/', {
        'comment': 'hack',
    }, format='json')

    assert resp.status_code in DENIED, resp.content
    assert _class_state(stale_teacher) == before


def test_stale_teacher_cannot_suspend_or_reactivate_another_orgs_class(api_client, stale_teacher):
    before = _class_state(stale_teacher)
    _login(api_client, stale_teacher['teacher'])

    suspend = api_client.post(f'/api/classes/{stale_teacher["class_a"].id}/suspend/', {
        'suspend_reason': 'hack',
    }, format='json')
    reactivate = api_client.post(f'/api/classes/{stale_teacher["class_a"].id}/reactivate/', {}, format='json')

    assert suspend.status_code in DENIED, suspend.content
    assert reactivate.status_code in DENIED, reactivate.content
    assert _class_state(stale_teacher) == before


def test_stale_teacher_cannot_bulk_close_another_orgs_class(api_client, stale_teacher):
    """`bulk-close` recibe los ids en el body y comparte `_can_close_or_cancel`."""
    before = _class_state(stale_teacher)
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.post('/api/classes/bulk-close/', {
        'class_ids': [stale_teacher['class_a'].id], 'action': 'complete_early',
        'comment': 'hack',
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['updated_ids'] == [], resp.content
    assert _class_state(stale_teacher) == before


def test_stale_teacher_cannot_reach_the_other_orgs_enrollments(api_client, stale_teacher):
    """`EnrollmentViewSet` scopea al profe por `gym_class__teacher_id`, con el mismo hueco."""
    _login(api_client, stale_teacher['teacher'])

    listing = api_client.get('/api/enrollments/')
    cancel = api_client.post(
        f'/api/enrollments/{stale_teacher["enrollment_a"].id}/cancel/', {}, format='json',
    )

    assert listing.status_code == 200, listing.content
    rows = listing.json()
    rows = rows['results'] if isinstance(rows, dict) else rows
    assert not [r for r in rows if r['id'] == stale_teacher['enrollment_a'].id], rows
    assert cancel.status_code in DENIED, cancel.content
    stale_teacher['enrollment_a'].refresh_from_db()
    assert stale_teacher['enrollment_a'].status == 'active'


def test_stale_teacher_cannot_enroll_students_in_another_orgs_class(api_client, stale_teacher, make_user):
    """`perform_create` del profe: la clase ajena no puede recibir inscripciones."""
    otro = make_user('alu_a2', organization=stale_teacher['org_a'], role='student', email='alu_a2@a.cl')
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': stale_teacher['class_a'].id, 'student': otro.id,
    }, format='json')

    assert resp.status_code in DENIED | {400}, resp.content
    assert not Enrollment.objects.filter(gym_class=stale_teacher['class_a'], student=otro).exists()


def test_stale_teacher_does_not_see_the_other_orgs_payment_records(api_client, stale_teacher):
    """`TeacherPaymentRecordViewSet` scopea al profe por `teacher_id` sin organización."""
    from core.models import TeacherPaymentRecord
    record = TeacherPaymentRecord.objects.create(
        teacher=stale_teacher['teacher'], class_instance=stale_teacher['class_a'],
        total_amount=12345,
    )
    _login(api_client, stale_teacher['teacher'])

    resp = api_client.get('/api/teacher-payments/my/')

    assert resp.status_code == 200, resp.content
    rows = resp.json()
    rows = rows['results'] if isinstance(rows, dict) else rows
    assert not [r for r in rows if r['id'] == record.id], (
        f'un pago calculado sobre una clase de otra organización se filtró: {rows}'
    )


# ---------------------------------------------------------------------------
# Regresión: el profe alineado con su organización conserva TODO su acceso
# ---------------------------------------------------------------------------

@pytest.fixture
def aligned_teacher(make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('profe', organization=org, role='teacher', email='profe@gym.cl')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Mi clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return {'teacher': teacher, 'gym_class': gym_class, 'student': student}


def test_aligned_teacher_keeps_full_access_to_its_own_class(api_client, aligned_teacher):
    """Contra-prueba: el acotamiento por organización no le quita nada al profe legítimo."""
    _login(api_client, aligned_teacher['teacher'])
    class_id = aligned_teacher['gym_class'].id

    listing = api_client.get('/api/classes/')
    rows = listing.json()
    rows = rows['results'] if isinstance(rows, dict) else rows
    assert [r for r in rows if r['id'] == class_id], 'el profe dejó de ver su propia clase'

    assert api_client.get(f'/api/classes/{class_id}/enrolled-students/').status_code == 200
    assert api_client.get(f'/api/classes/{class_id}/enrollable-students/').status_code == 200
    assert api_client.post(f'/api/classes/{class_id}/attendance/', {
        'attendances': [{'student_id': aligned_teacher['student'].id, 'status': 'present'}],
    }, format='json').status_code == 200
    assert api_client.post(f'/api/classes/{class_id}/suspend/', {
        'suspend_reason': 'lluvia',
    }, format='json').status_code == 200
    assert api_client.post(f'/api/classes/{class_id}/reactivate/', {}, format='json').status_code == 200
    assert api_client.post(f'/api/classes/{class_id}/cancel/', {
        'comment': 'se cayó el techo',
    }, format='json').status_code == 200


def test_registered_substitute_teacher_can_operate_assigned_class(api_client, make_organization,
                                                                  make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    titular = make_user('titular', organization=org, role='teacher', email='titular@gym.cl')
    substitute = make_user('suplente', organization=org, role='teacher', email='suplente@gym.cl')
    student = make_user('alu-sub', organization=org, role='student', email='alu-sub@gym.cl')
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=titular, name='Clase con suplente',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED, has_substitute=True, substitute_teacher=substitute,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')

    _login(api_client, substitute)
    listing = api_client.get('/api/classes/by-date/', {
        'date': start.date().isoformat(),
        'teacher_scope': 'mine',
    })
    assert listing.status_code == 200, listing.content
    assert [row for row in listing.json() if row['id'] == gym_class.id]

    assert api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/').status_code == 200
    attendance = api_client.post(f'/api/classes/{gym_class.id}/attendance/', {
        'attendances': [{'student_id': student.id, 'status': 'present'}],
    }, format='json')
    assert attendance.status_code == 200, attendance.content


def test_gym_admin_can_claim_and_operate_substitution_as_teacher(api_client, make_organization,
                                                                 make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    admin = make_user('admin-profe', organization=org, role='gym_admin', email='admin-profe@gym.cl')
    titular = make_user('titular-admin-sub', organization=org, role='teacher',
                        email='titular-admin-sub@gym.cl')
    student = make_user('alu-admin-sub', organization=org, role='student', email='alu-admin-sub@gym.cl')
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=titular, name='Clase libre',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')

    _login(api_client, admin)
    coverable = api_client.get('/api/classes/coverable/', {'date': start.date().isoformat()})
    assert coverable.status_code == 200, coverable.content
    assert [row for row in coverable.json() if row['id'] == gym_class.id and row['can_claim_substitution']]

    claim = api_client.post(f'/api/classes/{gym_class.id}/claim-substitution/', {}, format='json')
    assert claim.status_code == 200, claim.content
    gym_class.refresh_from_db()
    assert gym_class.has_substitute is True
    assert gym_class.substitute_teacher_id == admin.id

    mine = api_client.get('/api/classes/by-date/', {
        'date': start.date().isoformat(),
        'teacher_scope': 'mine',
    })
    assert mine.status_code == 200, mine.content
    assert [row for row in mine.json() if row['id'] == gym_class.id]

    attendance = api_client.post(f'/api/classes/{gym_class.id}/attendance/', {
        'attendances': [{'student_id': student.id, 'status': 'present'}],
    }, format='json')
    assert attendance.status_code == 200, attendance.content


def test_aligned_teacher_still_sees_its_enrollments_and_payments(api_client, aligned_teacher):
    """Regresión de los otros dos querysets que se acotan."""
    from core.models import TeacherPaymentRecord
    record = TeacherPaymentRecord.objects.create(
        teacher=aligned_teacher['teacher'], class_instance=aligned_teacher['gym_class'],
        total_amount=5000,
    )
    _login(api_client, aligned_teacher['teacher'])

    enrollments = api_client.get('/api/enrollments/')
    payments = api_client.get('/api/teacher-payments/my/')

    assert enrollments.status_code == 200, enrollments.content
    rows = enrollments.json()
    rows = rows['results'] if isinstance(rows, dict) else rows
    assert rows, 'el profe dejó de ver las inscripciones de su clase'

    assert payments.status_code == 200, payments.content
    prows = payments.json()
    prows = prows['results'] if isinstance(prows, dict) else prows
    assert [r for r in prows if r['id'] == record.id], 'el profe dejó de ver su propio pago'
