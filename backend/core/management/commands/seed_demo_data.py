import json
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ClassTemplate,
    ClassType,
    ConsumptionLog,
    Discipline,
    Enrollment,
    GymClass,
    Organization,
    Plan,
    StudentPlan,
    TeacherPaymentRule,
)

User = get_user_model()

# Orgs canónicos: sus usuarios usan usernames globales sin sufijo (p.ej. r2b-qa
# es la org real de R2B). Cualquier otro org (e2e-gym) sufija los usernames para
# NO reasignar usuarios existentes de un org canónico.
CANONICAL_SLUGS = {'tymro-demo', 'r2b-qa'}


class Command(BaseCommand):
    help = 'Puebla datos demo para autenticación, multi-organización y el loop de asistencia.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org',
            dest='org_slug',
            default='tymro-demo',
            help='Slug de la organización primaria a poblar (default: tymro-demo).',
        )

    def _u(self, base):
        """Aplica el sufijo de org al username para aislar orgs no canónicos."""
        return f'{base}{self.user_suffix}'

    def handle(self, *args, **options):
        slug = options.get('org_slug') or 'tymro-demo'
        self.user_suffix = '' if slug in CANONICAL_SLUGS else '_' + ''.join(c for c in slug if c.isalnum())
        org, _ = Organization.objects.get_or_create(
            slug=slug,
            defaults={
                'name': 'R2B Fight Club QA' if slug == 'r2b-qa' else 'TYMRO Demo Gym',
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
            username=self._u('gymadmin'),
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
                username=self._u(username),
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
                username=self._u(username),
                password='student123',
                role=User.Role.STUDENT,
                email=f'{username}@tymro.local',
                first_name=first_name,
                last_name=last_name,
                organization=org,
                branch=branch,
            )

        fixtures = self._seed_attendance_flow(org, branch_central, branch_norte, gym_admin, teachers, students)

        self._print_e2e_fixtures(org, gym_admin, fixtures)
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

        fixtures = self._seed_e2e_fixtures(
            org=org,
            branch=branch_central,
            teacher=teacher_central,
            branch_alt=branch_norte,
            teacher_alt=teacher_norte,
            class_type=class_types['Grupal'],
            discipline=disciplines['Funcional'],
            discipline_alt=disciplines['Yoga'],
            plan=plan,
            students=students,
            live_class=live_class,
            now=now,
            today=today,
        )

        # Fixtures deterministas de cálculo de pago a profesor (solo para el org E2E
        # de gym_admin). El motor calcula al cerrar la clase; aquí dejamos los records
        # listos para que la suite asierte montos exactos vía la API de resumen.
        if org.slug == 'e2e-gym':
            fixtures['payment_calc'] = self._seed_payment_calc_fixtures(
                org, branch_central, gym_admin, now,
            )

        return fixtures

    def _seed_e2e_fixtures(self, *, org, branch, teacher, branch_alt, teacher_alt,
                           class_type, discipline, discipline_alt, plan,
                           students, live_class, now, today):
        """Crea fixtures DETERMINISTAS para la suite E2E (Playwright): clases con
        nombre único reservables/llenas/solapadas, una serie con plantilla para
        recurrencia, alumnos en estados de rechazo y una organización foránea para
        el test de aislamiento multitenancy. Devuelve un dict con ids/nombres que el
        comando imprime como línea machine-readable (``TYMRO_E2E_FIXTURES=...``)."""
        student2 = students['student2']

        def future(days_ahead, hour, minute=0):
            return (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

        # Clases reservables (capacidad amplia, sin inscripciones previas del alumno).
        reservable_a = self._create_class(
            org, branch, teacher, class_type, discipline,
            name='E2E Reservable A', start=future(10, 7), duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )
        reservable_b = self._create_class(
            org, branch, teacher, class_type, discipline,
            name='E2E Reservable B', start=future(11, 7), duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )

        # Clase de OTRA disciplina y OTRO profesor/sucursal: da variedad para que
        # los filtros (disciplina / profesor) discriminen de forma significativa.
        yoga_class = self._create_class(
            org, branch_alt, teacher_alt, class_type, discipline_alt,
            name='E2E Yoga Norte', start=future(9, 18), duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )

        # Clase a tope de cupo (capacity=1, ya ocupada por otro alumno).
        full_class = self._create_class(
            org, branch, teacher, class_type, discipline,
            name='E2E Cupo Lleno', start=future(12, 7), duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )
        full_class.capacity = 1
        full_class.save(update_fields=['capacity', 'updated_at'])
        self._enroll(full_class, [student2])

        # Dos clases en el MISMO horario para forzar solape al reservar ambas.
        overlap_start = future(13, 13)
        overlap_1 = self._create_class(
            org, branch, teacher, class_type, discipline,
            name='E2E Solape 1', start=overlap_start, duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )
        overlap_2 = self._create_class(
            org, branch, teacher, class_type, discipline,
            name='E2E Solape 2', start=overlap_start, duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )

        # Serie con plantilla, para el flujo de recurrencia (inscribir/pausar/...).
        # Limpiamos plantillas previas del org (cascada borra RecurringEnrollment),
        # así re-suscribirse siempre funciona y no se acumula basura entre corridas.
        ClassTemplate.objects.filter(organization=org).delete()
        series_start = future(14, 8)
        template = ClassTemplate.objects.create(
            organization=org,
            branch=branch,
            teacher=teacher,
            class_type=class_type,
            discipline=discipline,
            name='E2E Serie Semanal',
            weekday=series_start.weekday(),
            start_time=time(series_start.hour, 0),
            end_time=time(series_start.hour + 1, 0),
            capacity=20,
            start_date=today,
            is_active=True,
        )
        series_class = self._create_class(
            org, branch, teacher, class_type, discipline,
            name='E2E Serie Semanal', start=series_start, duration_minutes=60,
            status=GymClass.Status.SCHEDULED,
        )
        series_class.class_template = template
        series_class.save(update_fields=['class_template', 'updated_at'])

        # Alumnos en estados de rechazo (mismo org). Password común: student123.
        bad_students = self._seed_rejection_students(org, branch, plan, today)

        # Organización FORÁNEA con una clase, para el test de aislamiento.
        foreign = self._seed_foreign_org(org, now)

        return {
            'live_class_id': live_class.id,
            'live_class_name': live_class.name,
            'filters': {
                'discipline_main': discipline.name,
                'discipline_alt': discipline_alt.name,
                'teacher_main': teacher.get_full_name() or teacher.username,
                'teacher_alt': teacher_alt.get_full_name() or teacher_alt.username,
            },
            'reservable_a': {'id': reservable_a.id, 'name': reservable_a.name},
            'reservable_b': {'id': reservable_b.id, 'name': reservable_b.name},
            'yoga_class': {'id': yoga_class.id, 'name': yoga_class.name},
            'full_class': {'id': full_class.id, 'name': full_class.name},
            'overlap_1': {'id': overlap_1.id, 'name': overlap_1.name},
            'overlap_2': {'id': overlap_2.id, 'name': overlap_2.name},
            'series': {
                'template_id': template.id,
                'class_id': series_class.id,
                'name': series_class.name,
            },
            'rejection_students': bad_students,
            'foreign': foreign,
        }

    def _seed_rejection_students(self, org, branch, plan, today):
        """Tres alumnos para los rechazos críticos. Idempotente: limpia sus planes."""
        result = {}

        no_plan = self._create_or_update_user(
            username=self._u('e2e_noplan'), password='student123', role=User.Role.STUDENT,
            email='e2e_noplan@tymro.local', first_name='Sin', last_name='Plan',
            organization=org, branch=branch,
        )
        StudentPlan.objects.filter(user=no_plan).delete()
        result['no_plan'] = no_plan.username

        no_balance = self._create_or_update_user(
            username=self._u('e2e_nobalance'), password='student123', role=User.Role.STUDENT,
            email='e2e_nobalance@tymro.local', first_name='Sin', last_name='Saldo',
            organization=org, branch=branch,
        )
        StudentPlan.objects.filter(user=no_balance).delete()
        StudentPlan.objects.create(
            user=no_balance, plan=plan,
            start_date=today - timedelta(days=5), end_date=today + timedelta(days=25),
            total_classes=5, classes_used=5, is_active=True,
        )
        result['no_balance'] = no_balance.username

        unpaid = self._create_or_update_user(
            username=self._u('e2e_unpaid'), password='student123', role=User.Role.STUDENT,
            email='e2e_unpaid@tymro.local', first_name='Matricula', last_name='Impaga',
            organization=org, branch=branch,
        )
        StudentPlan.objects.filter(user=unpaid).delete()
        StudentPlan.objects.create(
            user=unpaid, plan=plan,
            start_date=today - timedelta(days=5), end_date=today + timedelta(days=25),
            total_classes=12, classes_used=0, is_active=True,
            enrollment_fee=25000, enrollment_fee_paid_at=None,
        )
        result['unpaid'] = unpaid.username

        return result

    def _seed_foreign_org(self, primary_org, now):
        """Org distinta + 1 clase, para verificar que un alumno de la org primaria
        NO puede acceder a recursos ajenos (espera 404)."""
        foreign_org, _ = Organization.objects.get_or_create(
            slug=f'{primary_org.slug}-foreign',
            defaults={'name': 'Org Foránea QA', 'country': 'Chile', 'city': 'Santiago'},
        )
        foreign_branch, _ = Branch.objects.get_or_create(
            organization=foreign_org, name='Sucursal Foránea',
            defaults={'code': 'FOR', 'address': 'Otra ciudad 1'},
        )
        GymClass.objects.filter(organization=foreign_org).delete()
        foreign_class = GymClass.objects.create(
            organization=foreign_org, branch=foreign_branch, name='E2E Foránea',
            start_datetime=now + timedelta(days=10),
            end_datetime=now + timedelta(days=10, hours=1),
            capacity=20, status=GymClass.Status.SCHEDULED,
        )
        return {
            'org_id': foreign_org.id,
            'org_slug': foreign_org.slug,
            'class_id': foreign_class.id,
            'class_name': foreign_class.name,
        }

    def _seed_payment_calc_fixtures(self, org, branch, gym_admin, now):
        """Escenarios DETERMINISTAS de cálculo de pago a profesor para el E2E.

        - FIJO: $5.000 por clase, independiente de alumnos.
        - ASISTENCIA (per_plan_price present_attendees 40%): % del precio-por-clase
          de los PRESENTES. PlanA $40k/4=$10k, PlanB $40k/8=$5k, ilimitado=$0 ->
          (10000+5000)*0.4 = 6000.
        - RESERVA (per_plan_price active_enrollments 60%): inscritos activos aunque
          falten. (10000+5000)*0.6 = 9000.
        """
        from core.services.teacher_payments import calculate_teacher_payment

        today = timezone.localdate()

        def make_plan(name, total, price, unlimited=False):
            p, _ = Plan.objects.get_or_create(
                organization=org,
                name=name,
                defaults={
                    'plan_type': Plan.PlanType.PACK,
                    'total_classes': total,
                    'unlimited_classes': unlimited,
                    'duration_days': 30,
                    'price': price,
                },
            )
            return p

        def make_student(uname, fname, plan_obj, total, price, unlimited=False):
            u = self._create_or_update_user(
                username=self._u(uname), password='student123', role=User.Role.STUDENT,
                email=f'{self._u(uname)}@tymro.local', first_name=fname, last_name='Pago',
                organization=org, branch=branch,
            )
            StudentPlan.objects.filter(user=u).delete()
            sp = StudentPlan.objects.create(
                user=u, plan=plan_obj, start_date=today - timedelta(days=2),
                end_date=today + timedelta(days=28), total_classes=total,
                unlimited_classes=unlimited, classes_used=0, final_price=price, is_active=True,
            )
            return u, sp

        def make_teacher(uname, fname):
            return self._create_or_update_user(
                username=self._u(uname), password='teacher123', role=User.Role.TEACHER,
                email=f'{self._u(uname)}@tymro.local', first_name=fname, last_name='Pago',
                organization=org, branch=branch,
            )

        plan_a = make_plan('E2E Pago A 4/40k', 4, 40000)
        plan_b = make_plan('E2E Pago B 8/40k', 8, 40000)
        plan_il = make_plan('E2E Pago Ilimitado', 0, 0, unlimited=True)
        s_a, sp_a = make_student('s_pago_a', 'AlumnoA', plan_a, 4, 40000)
        s_b, sp_b = make_student('s_pago_b', 'AlumnoB', plan_b, 8, 40000)
        s_il, sp_il = make_student('s_pago_il', 'AlumnoIlim', plan_il, 0, 0, unlimited=True)

        t_fijo = make_teacher('teacher_fijo', 'ProfeFijo')
        t_asis = make_teacher('teacher_asis', 'ProfeAsistencia')
        t_res = make_teacher('teacher_res', 'ProfeReserva')

        # Reglas activas (una por profe), sin restricción de sucursal/disciplina.
        TeacherPaymentRule.objects.filter(organization=org, teachers__in=[t_fijo, t_asis, t_res]).delete()
        r_fijo = TeacherPaymentRule.objects.create(
            organization=org, payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
            amount=5000, is_active=True,
        )
        r_fijo.teachers.add(t_fijo)
        r_asis = TeacherPaymentRule.objects.create(
            organization=org, payment_type=TeacherPaymentRule.PaymentType.PER_PLAN_PRICE,
            per_plan_price_base=TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES,
            amount=40, is_active=True,
        )
        r_asis.teachers.add(t_asis)
        r_res = TeacherPaymentRule.objects.create(
            organization=org, payment_type=TeacherPaymentRule.PaymentType.PER_PLAN_PRICE,
            per_plan_price_base=TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS,
            amount=60, is_active=True,
        )
        r_res.teachers.add(t_res)

        start = now - timedelta(hours=2)

        def completed_class(name, teacher):
            return GymClass.objects.create(
                organization=org, branch=branch, teacher=teacher, name=name,
                start_datetime=start, end_datetime=start + timedelta(hours=1),
                status=GymClass.Status.COMPLETED, created_by=gym_admin,
            )

        def enroll(gym_class, student, student_plan, present, status='active'):
            Enrollment.objects.create(gym_class=gym_class, student=student, status=status)
            if student_plan is not None:
                ConsumptionLog.objects.create(user=student, student_plan=student_plan, class_instance=gym_class)
            if present:
                Attendance.objects.create(gym_class=gym_class, student=student, status=Attendance.Status.PRESENT)

        # FIJO -> 5000 (3 presentes, da igual cuántos)
        c_fijo = completed_class('E2E Pago Fijo', t_fijo)
        enroll(c_fijo, s_a, sp_a, present=True)
        enroll(c_fijo, s_b, sp_b, present=True)
        enroll(c_fijo, s_il, sp_il, present=True)
        calculate_teacher_payment(c_fijo)

        # ASISTENCIA 40% -> (10000+5000)*0.4 = 6000 (ilimitado aporta 0)
        c_asis = completed_class('E2E Pago Asistencia', t_asis)
        enroll(c_asis, s_a, sp_a, present=True)
        enroll(c_asis, s_b, sp_b, present=True)
        enroll(c_asis, s_il, sp_il, present=True)
        calculate_teacher_payment(c_asis)

        # RESERVA 60% -> (10000+5000)*0.6 = 9000 (s_b inscrito pero ausente igual aporta)
        c_res = completed_class('E2E Pago Reserva', t_res)
        enroll(c_res, s_a, sp_a, present=True)
        enroll(c_res, s_b, sp_b, present=False)
        calculate_teacher_payment(c_res)

        self.stdout.write('Fixtures de cálculo de pago creadas (fijo=5000, asistencia=6000, reserva=9000).')
        return {
            'fijo': {'teacher': t_fijo.username, 'expected': 5000},
            'asistencia': {'teacher': t_asis.username, 'expected': 6000},
            'reserva': {'teacher': t_res.username, 'expected': 9000},
        }

    def _print_e2e_fixtures(self, org, gym_admin, fixtures):
        """Imprime una línea parseable que global-setup.js captura para los tests."""
        payload = {
            'org_slug': org.slug,
            'org_id': org.id,
            'attendance_screen_code': org.attendance_screen_code,
            'gym_admin': {'username': gym_admin.username, 'password': 'gymadmin123'},
            'student': {'username': self._u('student1'), 'password': 'student123'},
            **fixtures,
        }
        self.stdout.write('TYMRO_E2E_FIXTURES=' + json.dumps(payload, ensure_ascii=False))

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
