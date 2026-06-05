from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
        ('core', '0002_branding_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='gymclass',
            old_name='title',
            new_name='name',
        ),
        migrations.RenameField(
            model_name='gymclass',
            old_name='starts_at',
            new_name='start_datetime',
        ),
        migrations.RenameField(
            model_name='gymclass',
            old_name='ends_at',
            new_name='end_datetime',
        ),
        migrations.RunSQL(
            sql=[
                "UPDATE core_gymclass SET teacher_id = NULL;",
                "DELETE FROM core_enrollment;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterModelOptions(
            name='gymclass',
            options={'ordering': ['-start_datetime']},
        ),
        migrations.AlterModelOptions(
            name='enrollment',
            options={'ordering': ['created_at']},
        ),
        migrations.RemoveField(
            model_name='enrollment',
            name='checked_in_at',
        ),
        migrations.RemoveField(
            model_name='gymclass',
            name='notes',
        ),
        migrations.RemoveField(
            model_name='gymclass',
            name='status',
        ),
        migrations.AddField(
            model_name='gymclass',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='enrollment',
            name='status',
            field=models.CharField(choices=[('active', 'Activa'), ('cancelled', 'Cancelada')], default='active', max_length=20),
        ),
        migrations.AlterField(
            model_name='enrollment',
            name='student',
            field=models.ForeignKey(on_delete=models.CASCADE, related_name='class_enrollments', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='gymclass',
            name='teacher',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='teaching_classes', to=settings.AUTH_USER_MODEL),
        ),
    ]
