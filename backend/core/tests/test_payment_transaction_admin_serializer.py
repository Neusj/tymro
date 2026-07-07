from datetime import date

import pytest

from core.models import PaymentTransaction, Plan, StudentPlan
from core.serializers import PaymentTransactionAdminSerializer


@pytest.fixture
def org(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def student(make_user, org):
    return make_user('ana', organization=org, role='student',
                     first_name='Ana', last_name='Pérez',
                     email='ana@gym.cl', phone='+56911111111')


def test_serializer_expone_datos_del_alumno_y_plan(org, student):
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, plan=plan, amount=20000, plan_amount=20000,
        currency='CLP', status='approved')

    data = PaymentTransactionAdminSerializer(tx).data

    assert data['student_name'] == 'Ana Pérez'
    assert data['student_email'] == 'ana@gym.cl'
    assert data['student_phone'] == '+56911111111'
    assert data['plan_name'] == 'Mensual'
    assert data['concept'] == 'Plan: Mensual'
    assert data['status'] == 'approved'
    assert data['activated_student_plan'] is False


def test_serializer_activated_student_plan_true_cuando_activo_plan(org, student):
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date=date(2026, 7, 1),
                                    end_date=date(2026, 7, 31), total_classes=8)
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, plan=plan, amount=20000, currency='CLP',
        status='approved', student_plan=sp)

    data = PaymentTransactionAdminSerializer(tx).data

    assert data['activated_student_plan'] is True
    assert data['student_plan'] == sp.id


def test_serializer_nombre_cae_a_username_y_concepto_matricula(org, student):
    student.first_name = ''
    student.last_name = ''
    student.save(update_fields=['first_name', 'last_name'])
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date=date(2026, 7, 1),
                                    end_date=date(2026, 7, 31), total_classes=8)
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, amount=5000, enrollment_fee_amount=5000,
        currency='CLP', status='pending', target_student_plan=sp)

    data = PaymentTransactionAdminSerializer(tx).data

    assert data['student_name'] == student.username
    assert data['plan_name'] is None
    assert data['concept'] == 'Matrícula'
