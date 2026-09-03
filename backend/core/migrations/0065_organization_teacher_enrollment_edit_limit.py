from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0064_organization_student_inactivity_grace_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='teacher_enrollment_edit_limit_minutes',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Minutos tras el fin de la clase en que el profesor puede inscribir alumnos.',
                validators=[django.core.validators.MaxValueValidator(1440)],
            ),
        ),
    ]
