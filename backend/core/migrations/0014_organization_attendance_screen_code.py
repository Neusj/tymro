from django.db import migrations, models
import core.models


def populate_attendance_screen_codes(apps, schema_editor):
    Organization = apps.get_model('core', 'Organization')
    used_codes = set(
        Organization.objects.exclude(attendance_screen_code='').values_list('attendance_screen_code', flat=True)
    )

    for organization in Organization.objects.all():
        if organization.attendance_screen_code:
            continue
        code = core.models.generate_attendance_screen_code()
        while code in used_codes:
            code = core.models.generate_attendance_screen_code()
        organization.attendance_screen_code = code
        organization.save(update_fields=['attendance_screen_code'])
        used_codes.add(code)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_plan_organization'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='attendance_screen_code',
            field=models.CharField(
                blank=True,
                default='',
                max_length=32,
            ),
        ),
        migrations.RunPython(populate_attendance_screen_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='organization',
            name='attendance_screen_code',
            field=models.CharField(
                default=core.models.generate_attendance_screen_code,
                max_length=32,
                unique=True,
            ),
        ),
    ]
