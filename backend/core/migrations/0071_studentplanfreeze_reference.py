import uuid

from django.db import migrations, models


def assign_freeze_references(apps, schema_editor):
    StudentPlanFreeze = apps.get_model('core', 'StudentPlanFreeze')
    for freeze in StudentPlanFreeze.objects.filter(reference__isnull=True).iterator():
        freeze.reference = uuid.uuid4()
        freeze.save(update_fields=['reference'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0070_teacher_payout_ranges'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentplanfreeze',
            name='reference',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(assign_freeze_references, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='studentplanfreeze',
            name='reference',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
