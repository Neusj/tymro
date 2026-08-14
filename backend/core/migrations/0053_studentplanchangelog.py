from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0052_enrollment_recurring_resync_blocked'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentPlanChangeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('field', models.CharField(max_length=80)),
                ('old_value', models.TextField(blank=True, default='')),
                ('new_value', models.TextField(blank=True, default='')),
                ('reason', models.TextField(blank=True, default='')),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_plan_changes', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='student_plan_change_logs', to='core.organization')),
                ('student_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='change_logs', to='core.studentplan')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='studentplanchangelog',
            index=models.Index(fields=['student_plan', 'created_at'], name='core_studen_student_81fe3f_idx'),
        ),
        migrations.AddIndex(
            model_name='studentplanchangelog',
            index=models.Index(fields=['organization', 'created_at'], name='core_studen_organiz_2548e9_idx'),
        ),
    ]
