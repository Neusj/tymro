from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0051_registered_substitutions'),
    ]

    operations = [
        migrations.AddField(
            model_name='enrollment',
            name='recurring_resync_blocked',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Bloquea que una recurrencia reactive esta instancia concreta tras '
                    'una cancelación individual.'
                ),
            ),
        ),
    ]
