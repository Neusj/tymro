"""Modelo: campo rut en CustomUser + UniqueConstraint(organization, rut).

Invariantes de datos:
- Sin RUT se guarda NULL (nunca ''); múltiples NULL por org NO colisionan.
- Unicidad POR organización: el mismo RUT puede existir en distintas orgs,
  pero no repetirse dentro de la misma org.
La normalización a canónico es responsabilidad del serializer/importador, no
del modelo; aquí solo se prueban almacenamiento y constraint.
"""
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_rut_defaults_to_null(make_organization, make_user):
    org = make_organization('A')
    user = make_user('x', organization=org, role='student', email='x@a.local')
    assert user.rut is None


def test_same_rut_in_two_orgs_is_allowed(make_organization, make_user):
    org_a = make_organization('A')
    org_b = make_organization('B')
    u_a = make_user('a', organization=org_a, role='student', email='a@a.local', rut='12345678-5')
    u_b = make_user('b', organization=org_b, role='student', email='b@b.local', rut='12345678-5')
    assert u_a.rut == u_b.rut == '12345678-5'
    assert u_a.organization_id != u_b.organization_id


def test_dup_rut_same_org_violates_db_constraint(make_organization, make_user):
    org = make_organization('A')
    make_user('first', organization=org, role='student', email='f@a.local', rut='12345678-5')
    with pytest.raises(IntegrityError):
        make_user('second', organization=org, role='student', email='s@a.local', rut='12345678-5')


def test_multiple_null_ruts_same_org_do_not_collide(make_organization, make_user):
    org = make_organization('A')
    make_user('first', organization=org, role='student', email='f@a.local')
    u2 = make_user('second', organization=org, role='student', email='s@a.local')
    assert u2.rut is None
