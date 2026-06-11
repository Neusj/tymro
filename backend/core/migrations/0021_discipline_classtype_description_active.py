from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_teacherpayout'),
    ]

    operations = [
        # Campos opcionales nuevos. Defaults seguros para no romper filas existentes:
        # description='' y is_active=True se aplican a todas las filas actuales.
        migrations.AddField(
            model_name='classtype',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='classtype',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='discipline',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='discipline',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
    ]
