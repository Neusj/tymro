from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_customuser_rut_customuser_uniq_rut_per_org'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='pays_enrollment_fee',
            field=models.BooleanField(
                default=True,
                help_text='Si esta desmarcado, este alumno no debe pagar matricula anual.',
            ),
        ),
    ]
