from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0053_studentplanchangelog'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='teacher_attendance_edit_limit_minutes',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Minutos tras el fin de la clase en que el profesor puede editar asistencia.',
                validators=[django.core.validators.MaxValueValidator(1440)],
            ),
        ),
    ]
