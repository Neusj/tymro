"""PersonViewSet (/api/people/) debe estar scopeado por organización y restringido
a superadmin/gym_admin. Regresión de la fuga de escritura cross-tenant."""
import pytest
from rest_framework.test import APIClient

from core.models import Person

pytestmark = pytest.mark.django_db
PASSWORD = 'Passw0rd2026'
URL = '/api/people/'


def _login(c, u):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=u)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    t = c.post('/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host).json()['token']
    c.credentials(HTTP_AUTHORIZATION=f'Token {t}')


@pytest.fixture
def two_orgs(make_organization, make_user):
    a = make_organization()
    b = make_organization()
    make_user('gaa', organization=a, role='gym_admin')
    make_user('gab', organization=b, role='gym_admin')
    return {'a': a, 'b': b}


def test_gym_admin_create_forces_own_org(two_orgs):
    c = APIClient()
    _login(c, 'gaa')
    resp = c.post(
        URL,
        {'first_name': 'X', 'last_name': 'Y', 'role': 'student', 'organization': two_orgs['b'].id},
        format='json',
    )
    assert resp.status_code == 201, resp.content
    person = Person.objects.get(id=resp.json()['id'])
    assert person.organization_id == two_orgs['a'].id  # forzada a la del actor, NO la b


def test_gym_admin_cannot_edit_other_org_person(two_orgs):
    foreign = Person.objects.create(organization=two_orgs['b'], first_name='F', last_name='Z')
    c = APIClient()
    _login(c, 'gaa')
    resp = c.patch(f'{URL}{foreign.id}/', {'first_name': 'Hacked'}, format='json')
    assert resp.status_code in (403, 404)  # no visible / no autorizado
    foreign.refresh_from_db()
    assert foreign.first_name == 'F'


def test_student_cannot_write_people(make_organization, make_user):
    org = make_organization()
    make_user('stu', organization=org, role='student')
    c = APIClient()
    _login(c, 'stu')
    assert c.post(URL, {'first_name': 'X', 'last_name': 'Y'}, format='json').status_code == 403


def test_gym_admin_lists_only_own_org(two_orgs):
    Person.objects.create(organization=two_orgs['a'], first_name='Mine', last_name='A')
    Person.objects.create(organization=two_orgs['b'], first_name='Theirs', last_name='B')
    c = APIClient()
    _login(c, 'gaa')
    resp = c.get(URL)
    assert resp.status_code == 200
    data = resp.json()
    rows = data if isinstance(data, list) else data.get('results', [])
    names = {r['first_name'] for r in rows}
    assert 'Mine' in names
    assert 'Theirs' not in names
