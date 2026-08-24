from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_customuser_trial_eligible'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='student_benefit_activated_on',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='student_benefit_enabled',
            field=models.BooleanField(default=False, help_text='Beneficio comercial de estudiante; no reemplaza el rol de alumno.'),
        ),
        migrations.AddField(
            model_name='customuser',
            name='student_benefit_expires_on',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='student_benefit_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customuser',
            name='student_benefit_updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_benefit_updates', to=settings.AUTH_USER_MODEL),
        ),
    ]
