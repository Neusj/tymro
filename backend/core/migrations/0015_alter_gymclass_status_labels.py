from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_organization_attendance_screen_code'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gymclass',
            name='status',
            field=models.CharField(
                choices=[
                    ('scheduled', 'Reservada'),
                    ('in_progress', 'En progreso'),
                    ('completed', 'Completada'),
                    ('cancelled', 'Cancelada'),
                    ('completed_early', 'Completada anticipadamente'),
                ],
                default='scheduled',
                max_length=20,
            ),
        ),
    ]
