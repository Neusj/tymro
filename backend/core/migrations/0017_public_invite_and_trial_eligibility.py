from django.db import migrations, models

from core.models import generate_invite_token


def populate_invite_tokens(apps, schema_editor):
    """Asigna un token único a cada organización existente (el default callable
    no puede aplicarse en bloque sin colisionar la restricción unique)."""
    Organization = apps.get_model('core', 'Organization')
    for organization in Organization.objects.all():
        organization.public_invite_token = generate_invite_token()
        organization.save(update_fields=['public_invite_token'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_attendance_screen_session'),
    ]

    operations = [
        # 1) Campo nullable para no colisionar en filas existentes.
        migrations.AddField(
            model_name='organization',
            name='public_invite_token',
            field=models.CharField(max_length=64, null=True),
        ),
        # 2) Backfill de tokens únicos por organización.
        migrations.RunPython(populate_invite_tokens, noop_reverse),
        # 3) Estado final: unique + default callable.
        migrations.AlterField(
            model_name='organization',
            name='public_invite_token',
            field=models.CharField(default=generate_invite_token, max_length=64, unique=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='public_registration_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='gymclass',
            name='is_trial_eligible',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classtemplate',
            name='is_trial_eligible',
            field=models.BooleanField(default=False),
        ),
    ]
