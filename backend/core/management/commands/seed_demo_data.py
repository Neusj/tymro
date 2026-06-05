from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Branch, Organization

User = get_user_model()


class Command(BaseCommand):
    help = 'Puebla datos demo para autenticación y multi-organización inicial.'

    def handle(self, *args, **options):
        org, _ = Organization.objects.get_or_create(
            slug='tymro-demo',
            defaults={
                'name': 'TYMRO Demo Gym',
                'country': 'Chile',
                'city': 'Santiago',
                'primary_color': '#dc2626',
                'secondary_color': '#2563eb',
            },
        )

        branch_central, _ = Branch.objects.get_or_create(
            organization=org,
            name='Casa Matriz',
            defaults={
                'code': 'MATRIZ',
                'address': 'Av. Principal 123',
                'primary_color': '#f97316',
                'secondary_color': '#dc2626',
            },
        )

        branch_norte, _ = Branch.objects.get_or_create(
            organization=org,
            name='Sucursal Norte',
            defaults={
                'code': 'NORTE',
                'address': 'Calle Norte 456',
                'primary_color': '#2563eb',
                'secondary_color': '#f97316',
            },
        )

        self._create_or_update_user(
            username='superadmin',
            password='superadmin123',
            role=User.Role.SUPERADMIN,
            email='superadmin@tymro.local',
            first_name='Super',
            last_name='Admin',
            is_staff=True,
            is_superuser=True,
            organization=None,
            branch=None,
        )

        self._create_or_update_user(
            username='gymadmin',
            password='gymadmin123',
            role=User.Role.GYM_ADMIN,
            email='gymadmin@tymro.local',
            first_name='Gym',
            last_name='Admin',
            organization=org,
            branch=branch_central,
        )

        teachers = [
            ('teacher1', 'Camila', 'Rojas', branch_central),
            ('teacher2', 'Pedro', 'Leiva', branch_norte),
        ]
        for username, first_name, last_name, branch in teachers:
            self._create_or_update_user(
                username=username,
                password='teacher123',
                role=User.Role.TEACHER,
                email=f'{username}@tymro.local',
                first_name=first_name,
                last_name=last_name,
                organization=org,
                branch=branch,
            )

        students = [
            ('student1', 'Valentina', 'Diaz', branch_central),
            ('student2', 'Matias', 'Silva', branch_norte),
            ('student3', 'Josefa', 'Perez', branch_norte),
        ]
        for username, first_name, last_name, branch in students:
            self._create_or_update_user(
                username=username,
                password='student123',
                role=User.Role.STUDENT,
                email=f'{username}@tymro.local',
                first_name=first_name,
                last_name=last_name,
                organization=org,
                branch=branch,
            )

        self.stdout.write(self.style.SUCCESS('Datos demo creados/actualizados correctamente.'))

    def _create_or_update_user(self, username, password, **fields):
        user, created = User.objects.get_or_create(username=username, defaults=fields)

        for key, value in fields.items():
            setattr(user, key, value)

        user.is_active = True
        user.is_active_member = fields.get('role') != User.Role.SUPERADMIN
        user.set_password(password)
        user.save()

        action = 'Creado' if created else 'Actualizado'
        self.stdout.write(f'{action}: {username}')
