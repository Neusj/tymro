from django.db import migrations, models


def backfill_public_trial_eligibility(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.filter(
        role='student',
        organization__isnull=False,
        rut__isnull=True,
    ).update(trial_eligible=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_customuser_pays_enrollment_fee'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='trial_eligible',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_public_trial_eligibility, noop_reverse),
    ]
