from django.db import migrations, models
import django.db.models.deletion


def backfill_consumption_branch(apps, schema_editor):
    """Deriva `ConsumptionLog.branch` de la clase consumida.

    `GymClass.branch` es obligatoria, así que todo consumo existente tiene sucursal
    derivable y el backfill no deja huérfanos. Se actualiza por lotes agrupando por
    sucursal en vez de fila por fila.
    """
    ConsumptionLog = apps.get_model('core', 'ConsumptionLog')
    GymClass = apps.get_model('core', 'GymClass')

    pending = ConsumptionLog.objects.filter(branch__isnull=True)
    branch_ids = (
        GymClass.objects.filter(consumption_logs__in=pending)
        .values_list('branch_id', flat=True)
        .distinct()
    )
    for branch_id in set(branch_ids):
        if branch_id is None:
            continue
        ConsumptionLog.objects.filter(
            branch__isnull=True, class_instance__branch_id=branch_id
        ).update(branch_id=branch_id)


def backfill_student_plan_branch(apps, schema_editor):
    """Deriva `StudentPlan.branch` del alcance de su plan.

    En un despliegue real esto es un no-op y así debe ser: el `AddField` de arriba crea
    `Plan.branch` en NULL para todas las filas, así que ningún plan preexistente es
    exclusivo y no hay sede que heredar. Se mantiene por si la migración se aplica sobre
    una base donde los planes ya tienen sucursal (restauración parcial, entorno de
    pruebas). Las membresías de planes globales quedan en NULL a propósito: NULL es
    "sin sede registrada".
    """
    StudentPlan = apps.get_model('core', 'StudentPlan')
    Plan = apps.get_model('core', 'Plan')

    for plan_id, branch_id in Plan.objects.filter(branch__isnull=False).values_list('id', 'branch_id'):
        StudentPlan.objects.filter(plan_id=plan_id, branch__isnull=True).update(branch_id=branch_id)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_organization_trial_validity_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='branch',
            field=models.ForeignKey(
                blank=True,
                help_text='Vacío = plan global de la organización. Con sucursal = exclusivo de esa sede.',
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name='exclusive_plans',
                to='core.branch',
            ),
        ),
        migrations.AddField(
            model_name='studentplan',
            name='branch',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='student_plans',
                to='core.branch',
            ),
        ),
        migrations.AddField(
            model_name='consumptionlog',
            name='branch',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='consumption_logs',
                to='core.branch',
            ),
        ),
        # Los planes preexistentes quedan GLOBALES (branch=NULL), que es el comportamiento
        # actual: ninguno estaba acotado a una sede. Solo se derivan los datos derivables.
        migrations.RunPython(backfill_consumption_branch, migrations.RunPython.noop),
        migrations.RunPython(backfill_student_plan_branch, migrations.RunPython.noop),
    ]
