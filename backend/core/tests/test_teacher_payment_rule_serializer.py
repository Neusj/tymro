"""El serializer de reglas de pago debe aceptar las 6 modalidades válidas del
modelo (incluidas per_enrolled, per_hour, monthly_fixed que antes rechazaba) y
exigir base para per_plan_price."""
import pytest

from core.models import TeacherPaymentRule
from core.serializers import TeacherPaymentRuleSerializer

pytestmark = pytest.mark.django_db


class _Req:
    def __init__(self, user):
        self.user = user


@pytest.fixture
def gym_admin(make_organization, make_user):
    org = make_organization()
    return make_user('ga', organization=org, role='gym_admin')


@pytest.mark.parametrize('ptype', ['per_enrolled', 'per_hour', 'monthly_fixed'])
def test_serializer_accepts_previously_rejected_types(gym_admin, ptype):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': ptype, 'amount': 5000, 'is_active': True},
        context={'request': _Req(gym_admin)},
    )
    assert s.is_valid(), s.errors
    assert s.validated_data['payment_type'] == ptype


def test_serializer_accepts_fixed_and_per_student(gym_admin):
    for ptype in ('fixed_per_class', 'per_student'):
        s = TeacherPaymentRuleSerializer(
            data={'payment_type': ptype, 'amount': 5000},
            context={'request': _Req(gym_admin)},
        )
        assert s.is_valid(), s.errors


def test_serializer_rejects_unknown_type(gym_admin):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': 'bogus', 'amount': 1},
        context={'request': _Req(gym_admin)},
    )
    assert not s.is_valid()
    assert 'payment_type' in s.errors


def test_per_plan_price_requires_base(gym_admin):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': 'per_plan_price', 'amount': 40},
        context={'request': _Req(gym_admin)},
    )
    assert not s.is_valid()
    assert 'per_plan_price_base' in s.errors


def test_per_plan_price_accepts_present_and_active(gym_admin):
    for base in ('present_attendees', 'active_enrollments'):
        s = TeacherPaymentRuleSerializer(
            data={'payment_type': 'per_plan_price', 'amount': 40, 'per_plan_price_base': base},
            context={'request': _Req(gym_admin)},
        )
        assert s.is_valid(), s.errors
        assert s.validated_data['per_plan_price_base'] == base


def test_negative_amount_rejected(gym_admin):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': 'monthly_fixed', 'amount': -1},
        context={'request': _Req(gym_admin)},
    )
    assert not s.is_valid()
    assert 'amount' in s.errors
