from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0054_organization_teacher_attendance_edit_limit'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentPlanFreeze',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('start_date', models.DateField()),
                ('planned_end_date', models.DateField()),
                ('actual_end_date', models.DateField(blank=True, null=True)),
                ('reason', models.TextField()),
                ('status', models.CharField(choices=[('active', 'Activa'), ('completed', 'Completada')], default='active', max_length=20)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('extension_days', models.PositiveIntegerField(default=0)),
                ('cancelled_future_enrollments', models.PositiveIntegerField(default=0)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_student_plan_freezes', to=settings.AUTH_USER_MODEL)),
                ('ended_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ended_student_plan_freezes', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='student_plan_freezes', to='core.organization')),
                ('student_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='freezes', to='core.studentplan')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='studentplanfreeze',
            index=models.Index(fields=['student_plan', 'status'], name='core_studen_student_ad2eee_idx'),
        ),
        migrations.AddIndex(
            model_name='studentplanfreeze',
            index=models.Index(fields=['organization', 'status', 'planned_end_date'], name='core_studen_organiz_ea3d6a_idx'),
        ),
        migrations.AddConstraint(
            model_name='studentplanfreeze',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'active')), fields=('student_plan',), name='uniq_active_freeze_per_student_plan'),
        ),
    ]
