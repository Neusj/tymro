from django.db import migrations


def delete_unused_pending_personalized_sessions(apps, schema_editor):
    PersonalizedClassSession = apps.get_model('core', 'PersonalizedClassSession')
    PersonalizedClassSession.objects.filter(
        status='pending',
        student__isnull=True,
        confirmed_at__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0059_personalized_session_finish'),
    ]

    operations = [
        migrations.RunPython(delete_unused_pending_personalized_sessions, migrations.RunPython.noop),
    ]
