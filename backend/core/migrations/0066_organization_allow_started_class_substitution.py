from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0065_organization_teacher_enrollment_edit_limit'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='allow_started_class_substitution',
            field=models.BooleanField(
                default=False,
                help_text='Permite que profesores tomen suplencias de clases ya comenzadas y no terminadas.',
            ),
        ),
    ]
