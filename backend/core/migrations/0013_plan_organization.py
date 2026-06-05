from django.db import migrations, models
import django.db.models.deletion


def assign_plan_organizations(apps, schema_editor):
    Organization = apps.get_model('core', 'Organization')
    Plan = apps.get_model('core', 'Plan')
    StudentPlan = apps.get_model('core', 'StudentPlan')

    fallback_org = Organization.objects.order_by('id').first()
    if not fallback_org:
        fallback_org = Organization.objects.create(
            name='Legacy Organization',
            slug='legacy-organization',
            country='',
            city='',
            is_active=True,
        )

    for plan in Plan.objects.all().order_by('id'):
        org_ids = list(
            StudentPlan.objects.filter(plan=plan, user__organization_id__isnull=False)
            .values_list('user__organization_id', flat=True)
            .distinct()
            .order_by('user__organization_id')
        )
        if not org_ids:
            plan.organization_id = fallback_org.id
            plan.save(update_fields=['organization'])
            continue

        primary_org_id = org_ids[0]
        plan.organization_id = primary_org_id
        plan.save(update_fields=['organization'])

        for org_id in org_ids[1:]:
            cloned = Plan.objects.create(
                organization_id=org_id,
                name=plan.name,
                plan_type=plan.plan_type,
                total_classes=plan.total_classes,
                duration_days=plan.duration_days,
                price=plan.price,
                discount_percentage=plan.discount_percentage,
                is_public=plan.is_public,
                is_active=plan.is_active,
            )
            StudentPlan.objects.filter(plan=plan, user__organization_id=org_id).update(plan=cloned)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_attendance_checked_at_attendance_source_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='organization',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='legacy_plans',
                to='core.organization',
            ),
        ),
        migrations.RunPython(assign_plan_organizations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='plan',
            name='organization',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='legacy_plans',
                to='core.organization',
            ),
        ),
    ]
