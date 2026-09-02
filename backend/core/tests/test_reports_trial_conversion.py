"""Reporte de conversión de la clase de prueba (P3.4 · parte 2, pieza 2) —
`core.services.reports_trial`.

Cada test fija una afirmación sobre "cuántos prospectos que probaron terminaron comprando", y
ninguna puede aflojarse "para que pase". Lo que se fija:

* qué es "usar la prueba" —reserva viva en una clase que se dictó y ya empezó— y qué NO
  (cancelada, agendada para el futuro);
* qué es "membresía de pago" —la regla de `plans._payment_status`, no `final_price > 0`—:
  FREE explícito no cuenta, pagar solo la matrícula no cuenta, una devolución revierte el
  numerador pero se publica aparte;
* las identidades declaradas: `converted`/`attended` son subconjuntos de `trials`, y la serie
  suma exactamente los totales;
* el filtro de sede, que SOLO aplica del lado del trial;
* el aislamiento por organización, con el caso peligroso del alumno que existe en dos
  tenants —trial en una, compra en la otra—;
* `unbacked_trial_flags`, publicado aparte y EXCLUIDO de la tasa;
* el endpoint: solo `gym_admin`, sede ajena 404, export CSV/XLSX.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import (Attendance, Branch, Enrollment, GymClass, ManualPayment,
                         PaymentTransaction, Plan, StudentPlan)
from core.services import reports_trial
from core.services.reports_base import GRANULARITY_DAY, ReportScope
from core.services.reports_trial import (build_trial_conversion_report,
                                         trial_conversion_export_spec)

pytestmark = pytest.mark.django_db

URL = '/api/reports/trial-conversion/'


# --------------------------------------------------------------------------------------
# Fixtures y helpers.
# --------------------------------------------------------------------------------------

@pytest.fixture
def org(make_organization):
    return make_organization('Gym Conversión')


@pytest.fixture
def other_org(make_organization):
    return make_organization('Gym Vecino Conversión')


@pytest.fixture
def branch(org):
    return Branch.objects.create(organization=org, name='Sede Centro')


@pytest.fixture
def student(make_user, org):
    return make_user('stu-conv', organization=org, role='student')


@pytest.fixture
def admin(make_user, org):
    return make_user('adm-conv', organization=org, role='gym_admin')


def _local(day, hour=10, minute=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hour, minute))


def _trial_class(org, branch, *, day, hour=10, capacity=10, name='Prueba'):
    """Clase dictada (`SCHEDULED` + `is_active=True` cumple `DICTATED_Q`) que ya empezó si
    `day` es de hoy hacia atrás — lo que la hace "held" para `_trial_students`."""
    start = _local(day, hour)
    return GymClass.objects.create(
        organization=org, branch=branch, name=name, start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=capacity,
        status=GymClass.Status.SCHEDULED, is_active=True, is_trial_eligible=True,
    )


def _book_trial(gym_class, student, *, status='active'):
    return Enrollment.objects.create(gym_class=gym_class, student=student, is_trial=True,
                                     status=status)


def _attend(gym_class, student, status=Attendance.Status.PRESENT):
    return Attendance.objects.create(gym_class=gym_class, student=student, status=status)


def _plan(org, *, price=30000, plan_type=Plan.PlanType.PACK, branch=None, total_classes=8,
         duration_days=30):
    return Plan.objects.create(
        organization=org, name=f'Plan {price}-{org.id}-{branch.id if branch else "g"}',
        plan_type=plan_type, total_classes=total_classes, unlimited_classes=False,
        duration_days=duration_days, price=price, branch=branch,
    )


def _membership(user, plan, *, start_date, end_date=None, branch=None, final_price=None):
    if end_date is None:
        end_date = start_date + timedelta(days=plan.duration_days)
    return StudentPlan.objects.create(
        user=user, plan=plan, organization_id=plan.organization_id, branch=branch,
        start_date=start_date, end_date=end_date, total_classes=plan.total_classes,
        unlimited_classes=plan.unlimited_classes, classes_used=0,
        final_price=plan.price if final_price is None else final_price,
    )


def _tx(org, student, membership, *, plan_amount, enrollment_fee_amount=0, status='approved',
       collected_at=None, refunded_at=None, refunded_amount=0):
    return PaymentTransaction.objects.create(
        organization=org, user=student, student_plan=membership,
        amount=Decimal(plan_amount) + Decimal(enrollment_fee_amount),
        plan_amount=Decimal(plan_amount), enrollment_fee_amount=Decimal(enrollment_fee_amount),
        status=status, collected_at=collected_at, refunded_at=refunded_at,
        refunded_amount=Decimal(refunded_amount),
    )


def _manual(org, membership, amount=10000, method=None):
    return ManualPayment.objects.create(
        organization=org, student_plan=membership, amount=Decimal(amount),
        method=method or ManualPayment.METHOD_CASH,
    )


def _scope(org, *, date_from, date_to, granularity=GRANULARITY_DAY, branch=None):
    return ReportScope(organization_id=org.id, date_from=date_from, date_to=date_to,
                       granularity=granularity, branch=branch)


# --------------------------------------------------------------------------------------
# 1. Usó la prueba y DESPUÉS pagó = CONVIRTIÓ.
# --------------------------------------------------------------------------------------

def test_a_student_who_used_the_trial_and_then_paid_counts_as_converted(org, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=10)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=1))
    _tx(org, student, membership, plan_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 1
    assert data['totals']['conversion_rate'] == 100.0


def test_the_report_publishes_prospect_detail_for_the_drilldown(org, branch, make_user):
    today = timezone.localdate()
    trial_day = today - timedelta(days=10)
    teacher = make_user('trial-detail-teacher', organization=org, role='teacher',
                        first_name='Ignacio', last_name='Duarte')
    student = make_user('trial-detail-student', organization=org, role='student',
                        first_name='Ana', last_name='Perez', email='ana@test.local',
                        phone='+56 9 1111 2222')
    gym_class = _trial_class(org, branch, day=trial_day, name='Boxeo')
    gym_class.teacher = teacher
    gym_class.save(update_fields=['teacher'])
    _book_trial(gym_class, student)
    _attend(gym_class, student)
    plan = _plan(org)
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=1))
    _tx(org, student, membership, plan_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert len(data['prospects']) == 1
    prospect = data['prospects'][0]
    assert prospect['student_id'] == student.id
    assert prospect['name'] == 'Ana Perez'
    assert prospect['email'] == 'ana@test.local'
    assert prospect['phone'] == '+56 9 1111 2222'
    assert prospect['trial_date'] == trial_day.isoformat()
    assert prospect['conversion_deadline'] == (trial_day + timedelta(days=60)).isoformat()
    assert prospect['attended'] is True
    assert prospect['converted'] is True
    assert prospect['conversion_status'] == 'converted'
    assert prospect['membership']['id'] == membership.id
    assert prospect['membership']['plan_name'] == plan.name
    assert prospect['trial_classes'][0]['name'] == 'Boxeo'
    assert prospect['trial_classes'][0]['branch_name'] == branch.name
    assert prospect['trial_classes'][0]['teacher_name'] == 'Ignacio Duarte'


def test_a_manual_payment_also_counts_as_converted(org, branch, student):
    """La conversión no exige MercadoPago: un cobro registrado a mano sobre la membresía
    también cuenta (misma regla que `_payment_status`)."""
    today = timezone.localdate()
    trial_day = today - timedelta(days=10)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=1))
    _manual(org, membership)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['converted'] == 1


# --------------------------------------------------------------------------------------
# 2. Usó la prueba y NO pagó = NO CONVIRTIÓ.
# --------------------------------------------------------------------------------------

def test_a_student_who_used_the_trial_and_never_paid_does_not_convert(org, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=10)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 0
    assert data['totals']['conversion_rate'] == 0.0


# --------------------------------------------------------------------------------------
# 3. La tasa de conversión, verificable a mano: 4 pruebas / 1 convertida = 25 %.
# --------------------------------------------------------------------------------------

def test_the_conversion_rate_is_verifiable_by_hand(org, branch, make_user):
    today = timezone.localdate()
    trial_day = today - timedelta(days=10)
    gym_class = _trial_class(org, branch, day=trial_day, capacity=10)
    plan = _plan(org)
    converted = make_user('trial-rate-1', organization=org, role='student')
    others = [make_user(f'trial-rate-{i}', organization=org, role='student') for i in (2, 3, 4)]
    for s in [converted, *others]:
        _book_trial(gym_class, s)
    membership = _membership(converted, plan, start_date=trial_day + timedelta(days=1))
    _tx(org, converted, membership, plan_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 4
    assert data['totals']['converted'] == 1
    assert data['totals']['conversion_rate'] == 25.0


# --------------------------------------------------------------------------------------
# 4. FREE explícito, matrícula sola, y devolución.
# --------------------------------------------------------------------------------------

def test_a_free_membership_with_explicit_zero_price_does_not_convert(org, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    _membership(student, plan, start_date=trial_day + timedelta(days=1), final_price=0)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 0


def test_paying_only_the_enrollment_fee_does_not_convert(org, branch, student):
    """`plan_amount == 0` en la transacción: pagó la matrícula, no el plan. Es la ambigüedad
    que 8.2 resolvió, y este reporte tiene que respetarla."""
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=1))
    _tx(org, student, membership, plan_amount=0, enrollment_fee_amount=5000)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 0


def test_a_refunded_purchase_does_not_convert_but_is_published_separately(org, branch,
                                                                          student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=1))
    _tx(org, student, membership, plan_amount=plan.price, status='refunded',
       collected_at=timezone.now(), refunded_at=timezone.now(),
       refunded_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 0
    assert data['totals']['refunded_conversions'] == 1


# --------------------------------------------------------------------------------------
# 5. Cancelada y de clase futura: fuera del denominador, publicadas aparte.
# --------------------------------------------------------------------------------------

def test_a_cancelled_trial_booking_does_not_enter_the_denominator(org, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student, status='cancelled')

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 0
    assert data['totals']['cancelled_trials'] == 1


def test_a_trial_booked_for_a_future_class_is_pending_not_used_yet(org, branch, student):
    today = timezone.localdate()
    future_day = today + timedelta(days=5)
    gym_class = _trial_class(org, branch, day=future_day)
    _book_trial(gym_class, student)

    data = build_trial_conversion_report(_scope(org, date_from=today, date_to=future_day))

    assert data['totals']['trials'] == 0
    assert data['totals']['pending_trials'] == 1


# --------------------------------------------------------------------------------------
# 6. Ventana de conversión (`CONVERSION_WINDOW_DAYS`) y `pending_window`.
# --------------------------------------------------------------------------------------

def test_a_purchase_outside_the_conversion_window_does_not_convert(org, branch, student,
                                                                    monkeypatch):
    monkeypatch.setattr(reports_trial, 'CONVERSION_WINDOW_DAYS', 5)
    today = timezone.localdate()
    trial_day = today - timedelta(days=30)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    # Compra 10 días después del trial, con una ventana de solo 5: queda AFUERA.
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=10))
    _tx(org, student, membership, plan_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 0
    # La ventana cerró hace mucho respecto de "hoy": el veredicto es definitivo.
    assert data['totals']['pending_window'] == 0


def test_pending_window_marks_trials_whose_verdict_can_still_change(org, branch, student,
                                                                    monkeypatch):
    monkeypatch.setattr(reports_trial, 'CONVERSION_WINDOW_DAYS', 30)
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['converted'] == 0
    assert data['totals']['pending_window'] == 1


# --------------------------------------------------------------------------------------
# 7. Aislamiento por organización — incluido el cruce peligroso trial→compra.
# --------------------------------------------------------------------------------------

def test_another_organizations_trials_and_purchases_never_leak_into_totals(
        org, other_org, branch, student, make_user):
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    foreign_branch = Branch.objects.create(organization=other_org, name='Sede vecina')
    foreign_student = make_user('trial-foreign', organization=other_org, role='student')
    foreign_class = _trial_class(other_org, foreign_branch, day=trial_day)
    _book_trial(foreign_class, foreign_student)
    foreign_plan = _plan(other_org)
    foreign_membership = _membership(foreign_student, foreign_plan,
                                     start_date=trial_day + timedelta(days=1),
                                     branch=foreign_branch)
    _tx(other_org, foreign_student, foreign_membership, plan_amount=foreign_plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 0


def test_a_student_who_tried_in_one_org_and_bought_in_another_does_not_convert_in_either(
        org, other_org, branch, student):
    """El alumno es CASCADE sobre la persona, no sobre el tenant: el mismo `CustomUser` puede
    tener una reserva de prueba en `org` y una membresía pagada en `other_org`. Ninguno de los
    dos reportes puede leer eso como una conversión: `org` ve el trial sin compra (su lado de
    la compra está scopeado a `org` y no encuentra la fila de `other_org`), y `other_org` ni
    siquiera ve el trial (su lado del trial está scopeado a la organización de la CLASE)."""
    today = timezone.localdate()
    trial_day = today - timedelta(days=10)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    other_branch = Branch.objects.create(organization=other_org, name='Sede ajena')
    other_plan = _plan(other_org, branch=other_branch)
    other_membership = _membership(student, other_plan, start_date=trial_day + timedelta(days=1),
                                   branch=other_branch)
    _tx(other_org, student, other_membership, plan_amount=other_plan.price)

    org_data = build_trial_conversion_report(
        _scope(org, date_from=trial_day, date_to=trial_day))
    other_org_data = build_trial_conversion_report(
        _scope(other_org, date_from=trial_day, date_to=trial_day))

    assert org_data['totals']['trials'] == 1
    assert org_data['totals']['converted'] == 0
    assert other_org_data['totals']['trials'] == 0
    assert other_org_data['totals']['converted'] == 0


# --------------------------------------------------------------------------------------
# 8. Filtro de sede: SOLO del lado del trial.
# --------------------------------------------------------------------------------------

def test_the_branch_filter_only_narrows_the_trial_side(org, make_user):
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    centro = Branch.objects.create(organization=org, name='Centro')
    norte = Branch.objects.create(organization=org, name='Norte')
    stu_centro = make_user('trial-branch-centro', organization=org, role='student')
    stu_norte = make_user('trial-branch-norte', organization=org, role='student')
    class_centro = _trial_class(org, centro, day=trial_day)
    class_norte = _trial_class(org, norte, day=trial_day)
    _book_trial(class_centro, stu_centro)
    _book_trial(class_norte, stu_norte)
    plan = _plan(org, branch=None)  # plan GLOBAL: no bloquea la compra por sede
    membership = _membership(stu_centro, plan, start_date=trial_day + timedelta(days=1),
                             branch=None)
    _tx(org, stu_centro, membership, plan_amount=plan.price)

    centro_data = build_trial_conversion_report(
        _scope(org, date_from=trial_day, date_to=trial_day, branch=centro))
    norte_data = build_trial_conversion_report(
        _scope(org, date_from=trial_day, date_to=trial_day, branch=norte))

    assert centro_data['totals']['trials'] == 1
    assert centro_data['totals']['converted'] == 1
    assert norte_data['totals']['trials'] == 1
    assert norte_data['totals']['converted'] == 0


def test_a_purchase_counts_regardless_of_its_own_branch(org, make_user):
    """El lado de la COMPRA no se filtra por sede aunque el reporte esté filtrado por sede:
    un alumno que probó en Centro y compró un plan EXCLUSIVO de Norte igual convierte para el
    reporte de Centro."""
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    centro = Branch.objects.create(organization=org, name='Centro')
    norte = Branch.objects.create(organization=org, name='Norte')
    student = make_user('trial-cross-branch', organization=org, role='student')
    gym_class = _trial_class(org, centro, day=trial_day)
    _book_trial(gym_class, student)
    plan_norte = _plan(org, branch=norte)
    membership = _membership(student, plan_norte, start_date=trial_day + timedelta(days=1),
                             branch=norte)
    _tx(org, student, membership, plan_amount=plan_norte.price)

    data = build_trial_conversion_report(
        _scope(org, date_from=trial_day, date_to=trial_day, branch=centro))

    assert data['totals']['trials'] == 1
    assert data['totals']['converted'] == 1


# --------------------------------------------------------------------------------------
# 9. `unbacked_trial_flags`: diagnóstico aparte, EXCLUIDO de la tasa.
# --------------------------------------------------------------------------------------

def test_unbacked_trial_flags_counts_users_with_the_flag_but_no_reservation(org, make_user):
    make_user('trial-ghost', organization=org, role='student', has_used_trial=True)
    today = timezone.localdate()

    data = build_trial_conversion_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['trials'] == 0
    assert data['unbacked_trial_flags']['students'] == 1
    assert data['unbacked_trial_flags']['excluded_from_rate'] is True


def test_a_student_backed_by_a_real_reservation_is_not_counted_as_unbacked(org, branch,
                                                                           student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=5)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    student.has_used_trial = True
    student.save(update_fields=['has_used_trial'])

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))

    assert data['unbacked_trial_flags']['students'] == 0


# --------------------------------------------------------------------------------------
# 10. Identidades: converted/attended ⊆ trials, Σ series == totals.
# --------------------------------------------------------------------------------------

def test_identities_hold_converted_and_attended_are_subsets_and_series_sums_to_totals(
        org, branch, make_user):
    today = timezone.localdate()
    day1, day2 = today - timedelta(days=2), today - timedelta(days=1)
    plan = _plan(org)
    converted_attended = make_user('trial-id-1', organization=org, role='student')
    converted_only = make_user('trial-id-2', organization=org, role='student')
    attended_only = make_user('trial-id-3', organization=org, role='student')
    neither = make_user('trial-id-4', organization=org, role='student')

    class_day1 = _trial_class(org, branch, day=day1, capacity=10)
    class_day2 = _trial_class(org, branch, day=day2, capacity=10)
    _book_trial(class_day1, converted_attended)
    _book_trial(class_day1, attended_only)
    _book_trial(class_day2, converted_only)
    _book_trial(class_day2, neither)
    _attend(class_day1, converted_attended)
    _attend(class_day1, attended_only)

    m1 = _membership(converted_attended, plan, start_date=day1 + timedelta(days=1))
    _tx(org, converted_attended, m1, plan_amount=plan.price)
    m2 = _membership(converted_only, plan, start_date=day2 + timedelta(days=1))
    _tx(org, converted_only, m2, plan_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=day1, date_to=day2))

    totals = data['totals']
    assert totals['trials'] == 4
    assert totals['converted'] == 2
    assert totals['attended'] == 2
    assert totals['converted'] <= totals['trials']
    assert totals['attended'] <= totals['trials']
    assert totals['converted_attended'] == 1

    for point in data['series']:
        assert point['converted'] <= point['trials']
        assert point['attended'] <= point['trials']
    assert sum(point['trials'] for point in data['series']) == totals['trials']
    assert sum(point['converted'] for point in data['series']) == totals['converted']
    assert sum(point['attended'] for point in data['series']) == totals['attended']


# --------------------------------------------------------------------------------------
# 11. Tasas viajan como `null` cuando el denominador es 0.
# --------------------------------------------------------------------------------------

def test_rates_travel_as_null_when_there_are_no_trials(org):
    today = timezone.localdate()

    data = build_trial_conversion_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['trials'] == 0
    assert data['totals']['conversion_rate'] is None
    assert data['totals']['attended_conversion_rate'] is None


# --------------------------------------------------------------------------------------
# 12. Export.
# --------------------------------------------------------------------------------------

def test_the_export_spec_mirrors_the_series_payload(org, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=1)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    plan = _plan(org)
    membership = _membership(student, plan, start_date=trial_day + timedelta(days=1))
    _tx(org, student, membership, plan_amount=plan.price)

    data = build_trial_conversion_report(_scope(org, date_from=trial_day, date_to=trial_day))
    spec = trial_conversion_export_spec(data)

    assert spec['header'][0] == 'Período'
    # Un bloque por punto de la serie + la fila informativa de canceladas/pendientes.
    assert len(spec['rows']) == len(data['series']) + 1
    assert spec['total_row'][0] == 'TOTAL'
    assert spec['total_row'][1] == data['totals']['trials']


def test_export_csv_returns_a_spreadsheet(api_client, org, admin, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=1)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': trial_day.isoformat(),
                                'date_to': trial_day.isoformat(), 'export': 'csv'})

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'].startswith('text/csv')
    assert 'conversion_prueba' in resp['Content-Disposition']
    content = resp.content.decode('utf-8-sig')
    assert 'TOTAL' in content


def test_export_xlsx_returns_a_workbook(api_client, org, admin, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=1)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': trial_day.isoformat(),
                                'date_to': trial_day.isoformat(), 'export': 'xlsx'})

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'] == ('application/vnd.openxmlformats-officedocument'
                                    '.spreadsheetml.sheet')
    assert 'conversion_prueba' in resp['Content-Disposition']


# --------------------------------------------------------------------------------------
# 13. El endpoint: solo `gym_admin`, sede ajena 404.
# --------------------------------------------------------------------------------------

def test_gym_admin_gets_the_report_via_http(api_client, org, admin, branch, student):
    today = timezone.localdate()
    trial_day = today - timedelta(days=3)
    gym_class = _trial_class(org, branch, day=trial_day)
    _book_trial(gym_class, student)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': trial_day.isoformat(),
                                'date_to': trial_day.isoformat()})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['totals']['trials'] == 1
    assert set(body) == {'period', 'filters', 'totals', 'previous', 'comparison',
                         'unbacked_trial_flags', 'series', 'prospects'}


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_no_other_organization_role_can_read_the_report(api_client, org, make_user, role):
    actor = make_user(f'{role}-trial', organization=org, role=role)
    api_client.force_authenticate(user=actor)

    resp = api_client.get(URL)

    assert resp.status_code == 403, resp.content


def test_superadmin_cannot_read_the_report_either(api_client, make_user):
    root = make_user('root-trial', organization=None, role='superadmin')
    api_client.force_authenticate(user=root)

    resp = api_client.get(URL)

    assert resp.status_code == 403, resp.content


def test_unauthenticated_request_is_rejected(api_client):
    assert api_client.get(URL).status_code == 401


def test_a_branch_of_another_organization_is_404(api_client, org, admin, other_org):
    foreign_branch = Branch.objects.create(organization=other_org, name='Sede ajena')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'branch_id': foreign_branch.id})

    assert resp.status_code == 404, resp.content
