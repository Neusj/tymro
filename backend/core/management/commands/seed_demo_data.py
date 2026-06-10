from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ClassType,
    Discipline,
    Enrollment,
    GymClass,
    Organization,
    Plan,
    StudentPlan,
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Puebla datos demo para autenticación, multi-organización y el loop de asistencia.'

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

        gym_admin = self._create_or_update_user(
            username='gymadmin',
            password='gymadmin123',
            role=User.Role.GYM_ADMIN,
            email='gymadmin@tymro.local',
            first_name='Gym',
            last_name='Admin',
            organization=org,
            branch=branch_central,
        )

        teachers = {}
        for username, first_name, last_name, branch in [
            ('teacher1', 'Camila', 'Rojas', branch_central),
            ('teacher2', 'Pedro', 'Leiva', branch_norte),
        ]:
            teachers[username] = self._create_or_update_user(
                username=username,
                password='teacher123',
                role=User.Role.TEACHER,
                email=f'{username}@tymro.local',
                first_name=first_name,
                last_name=last_name,
                organization=org,
                branch=branch,
            )

        students = {}
        for username, first_name, last_name, branch in [
            ('student1', 'Valentina', 'Diaz', branch_central),
            ('student2', 'Matias', 'Silva', branch_norte),
            ('student3', 'Josefa', 'Perez', branch_norte),
        ]:
            students[username] = self._create_or_update_user(
                username=username,
                password='student123',
                role=User.Role.STUDENT,
                email=f'{username}@tymro.local',
                first_name=first_name,
                last_name=last_name,
                organization=org,
                branch=branch,
            )

        self._seed_attendance_flow(org, branch_central, branch_norte, gym_admin, teachers, students)

        self.stdout.write(self.style.SUCCESS('Datos demo creados/actualizados correctamente.'))

    def _seed_attendance_flow(self, org, branch_central, branch_norte, gym_admin, teachers, students):
        """Puebla disciplinas, tipos, planes, clases (incluida una marcable AHORA),
        reservas y asistencias para poder demostrar el loop completo de asistencia.

        Idempotente: las clases/reservas/asistencias del gimnasio demo se regeneran
        en cada corrida (relativas a la hora actual) para que siempre haya una clase
        dentro de la ventana de hoy."""
        # Disciplinas y tipos de clase (estables por nombre).
        disciplines = {}
        for name in ['Funcional', 'Yoga', 'Spinning']:
            disciplines[name], _ = Discipline.objects.get_or_create(organization=org, name=name)

        class_types = {}
        for name, minutes in [('Grupal', 60), ('Personalizada', 45)]:
            class_types[name], _ = ClassType.objects.get_or_create(
                organization=org,
                name=name,
                defaults={'duration_minutes': minutes},
            )

        # Plan demo + StudentPlan activo para cada alumno (con saldo de clases).
        plan, _ = Plan.objects.get_or_create(
            organization=org,
            name='Plan Mensual 12',
            defaults={
                'plan_type': Plan.PlanType.MONTHLY,
                'total_classes': 12,
                'duration_days': 30,
                'price': 30000,
            },
        )
        today = timezone.localdate()
        for student in students.values():
            StudentPlan.objects.update_or_create(
                user=student,
                plan=plan,
                defaults={
                    'start_date': today - timedelta(days=5),
                    'end_date': today + timedelta(days=25),
                    'total_classes': plan.total_classes,
                    'classes_used': 2,
                    'is_active': True,
                },
            )

        # Regeneramos el set de clases demo para que sea relativo a "ahora".
        GymClass.objects.filter(organization=org).delete()

        now = timezone.now()
        student_list = list(students.values())
        teacher_central = teachers['teacher1']
        teacher_norte = teachers['teacher2']

        # 1) Clase EN CURSO marcable AHORA por QR: empezó hace 5 min (dentro de la
        #    ventana [-10, +15] min). Alumnos inscritos, sin asistencia aún.
        live_class = self._create_class(
            org, branch_central, teacher_central, class_types['Grupal'], disciplines['Funcional'],
            name='Funcional AM (en curso)',
            start=now - timedelta(minutes=5),
            duration_minutes=60,
            status=GymClass.Status.IN_PROGRESS,
            created_by=gym_admin,
        )
        self._enroll(live_class, student_list)

        # 2) Clases pasadas de hoy/ayer YA COMPLETADAS, con asistencias variadas.
        attendance_cycle = [
            Attendance.Status.PRESENT,
            Attendance.Status.ABSENT,
            Attendance.Status.NO_SHOW,
        ]
        past_specs = [
            ('Yoga (ayer)', branch_norte, teacher_norte, disciplines['Yoga'], now - timedelta(days=1, hours=2)),
            ('Spinning temprano', branch_central, teacher_central, disciplines['Spinning'], now - timedelta(hours=4)),
        ]
        for name, branch, teacher, discipline, start in past_specs:
            past_class = self._create_class(
                org, branch, teacher, class_types['Grupal'], discipline,
                name=name,
                start=start,
                duration_minutes=60,
                status=GymClass.Status.COMPLETED,
                created_by=gym_admin,
            )
            enrollments = self._enroll(past_class, student_list)
            for index, enrollment in enumerate(enrollments):
                marked_status = attendance_cycle[index % len(attendance_cycle)]
                Attendance.objects.create(
                    gym_class=past_class,
                    student=enrollment.student,
                    status=marked_status,
                    source=Attendance.Source.MANUAL,
                    marked_by=teacher,
                    marked_at=past_class.end_datetime,
                    checked_at=past_class.end_datetime,
                )

        # 3) Clases futuras a lo largo de la semana (programadas, reservables).
        future_specs = [
            ('Funcional PM', branch_central, teacher_central, disciplines['Funcional'], 1, 19),
            ('Yoga Flow', branch_norte, teacher_norte, disciplines['Yoga'], 2, 9),
            ('Spinning Power', branch_central, teacher_central, disciplines['Spinning'], 3, 18),
            ('Funcional Finde', branch_norte, teacher_norte, disciplines['Funcional'], 5, 11),
        ]
        for name, branch, teacher, discipline, days_ahead, hour in future_specs:
            start = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
            future_class = self._create_class(
                org, branch, teacher, class_types['Grupal'], discipline,
                name=name,
                start=start,
                duration_minutes=60,
                status=GymClass.Status.SCHEDULED,
                is_trial_eligible=(days_ahead in {1, 2}),
                created_by=gym_admin,
            )
            # Inscribimos a un par de alumnos para que tengan reservas futuras.
            self._enroll(future_class, student_list[:2])

        self.stdout.write(
            'Flujo de asistencia poblado: 1 clase en curso marcable ahora, '
            '2 completadas con asistencias y 4 futuras.'
        )

    def _create_class(self, org, branch, teacher, class_type, discipline, *, name, start,
                      duration_minutes, status, is_trial_eligible=False, created_by=None):
        return GymClass.objects.create(
            organization=org,
            branch=branch,
            teacher=teacher,
            class_type=class_type,
            discipline=discipline,
            name=name,
            start_datetime=start,
            end_datetime=start + timedelta(minutes=duration_minutes),
            capacity=20,
            is_trial_eligible=is_trial_eligible,
            status=status,
            created_by=created_by,
        )

    def _enroll(self, gym_class, students):
        enrollments = []
        for student in students:
            enrollment, _ = Enrollment.objects.get_or_create(
                gym_class=gym_class,
                student=student,
                defaults={'status': 'active'},
            )
            enrollments.append(enrollment)
        return enrollments

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
        return user
