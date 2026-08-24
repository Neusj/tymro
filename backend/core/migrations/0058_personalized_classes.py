from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0057_push_notifications'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='personalized_classes_enabled',
            field=models.BooleanField(default=False, help_text='Habilita el flujo de clases personalizadas por QR ad hoc.'),
        ),
        migrations.AlterField(
            model_name='plan',
            name='plan_type',
            field=models.CharField(choices=[('monthly', 'Mensual'), ('pack', 'Pack'), ('single_class', 'Clase suelta'), ('trial', 'Trial'), ('giftcard', 'Giftcard'), ('personalized', 'Clases personalizadas')], max_length=20),
        ),
        migrations.AddField(
            model_name='plan',
            name='allowed_personalized_teachers',
            field=models.ManyToManyField(blank=True, help_text='Vacío = cualquier profesor de la organización.', related_name='allowed_personalized_plans', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='plan',
            name='compatible_class_types',
            field=models.ManyToManyField(blank=True, help_text='Vacío = cualquier tipo de clase. Se usa para clases personalizadas.', related_name='compatible_plans', to='core.classtype'),
        ),
        migrations.AddField(
            model_name='plan',
            name='compatible_disciplines',
            field=models.ManyToManyField(blank=True, help_text='Vacío = cualquier disciplina. Se usa para clases personalizadas.', related_name='compatible_plans', to='core.discipline'),
        ),
        migrations.CreateModel(
            name='PersonalizedClassSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('qr_jti', models.CharField(max_length=64, unique=True)),
                ('qr_issued_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('qr_expires_at', models.DateTimeField()),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('confirmed', 'Confirmada')], default='pending', max_length=20)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='personalized_class_sessions', to='core.branch')),
                ('class_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='personalized_class_sessions', to='core.classtype')),
                ('confirmed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='confirmed_personalized_class_sessions', to=settings.AUTH_USER_MODEL)),
                ('discipline', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='personalized_class_sessions', to='core.discipline')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='personalized_class_sessions', to='core.organization')),
                ('student', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='personalized_class_sessions_attended', to=settings.AUTH_USER_MODEL)),
                ('student_plan', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='personalized_class_sessions', to='core.studentplan')),
                ('teacher', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='personalized_class_sessions_taught', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-qr_issued_at', '-id'],
                'indexes': [
                    models.Index(fields=['organization', 'status', 'qr_expires_at'], name='core_person_organiz_0a9c33_idx'),
                    models.Index(fields=['organization', 'teacher', 'confirmed_at'], name='core_person_organiz_fcd2d4_idx'),
                    models.Index(fields=['organization', 'student', 'confirmed_at'], name='core_person_organiz_b7f0db_idx'),
                ],
            },
        ),
        migrations.AddField(
            model_name='attendance',
            name='personalized_session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attendances', to='core.personalizedclasssession'),
        ),
        migrations.AlterField(
            model_name='consumptionlog',
            name='class_instance',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='consumption_logs', to='core.gymclass'),
        ),
        migrations.AddField(
            model_name='consumptionlog',
            name='personalized_session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='consumption_logs', to='core.personalizedclasssession'),
        ),
        migrations.AddConstraint(
            model_name='attendance',
            constraint=models.UniqueConstraint(condition=models.Q(('personalized_session__isnull', False)), fields=('personalized_session', 'student'), name='uniq_attendance_personalized_session_student'),
        ),
        migrations.AddConstraint(
            model_name='consumptionlog',
            constraint=models.UniqueConstraint(condition=models.Q(('personalized_session__isnull', False)), fields=('personalized_session',), name='uniq_consumption_personalized_session'),
        ),
    ]
