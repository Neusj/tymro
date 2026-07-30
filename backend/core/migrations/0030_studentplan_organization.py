"""Organización propia en StudentPlan (copia de `plan.organization`).

Espeja el patrón de `0013_plan_organization`: columna nullable → backfill → NOT NULL.

NO impone unicidad. Un alumno PUEDE tener varias membresías activas a la vez en la misma
organización —el caso normal es contratar dos disciplinas, p. ej. un plan de 4 BJJ y otro
de 8 kickboxing—, así que acá no va ningún índice único sobre (user, organization) ni un
pre-chequeo de duplicados: ese pre-chequeo abortaría la migración justamente para los
alumnos con más de un plan, que son datos válidos.
"""
from django.conf import settings
from django.db import migrations, models
from django.db.models import OuterRef, Subquery
import django.db.models.deletion


class DataInconsistency(RuntimeError):
    """Los datos existentes no admiten la invariante que esta migración impone."""


def backfill_organization(apps, schema_editor):
    StudentPlan = apps.get_model('core', 'StudentPlan')
    Plan = apps.get_model('core', 'Plan')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    # Fuente de verdad: la organización del PLAN, que es quien vendió la membresía.
    # `F('plan__organization_id')` no sirve —el ORM no admite joins en un UPDATE—, de ahí
    # la subconsulta correlacionada, que funciona igual en SQLite y en PostgreSQL.
    # `order_by()` vacío para que el `Meta.ordering` de Plan no se cuele en la subconsulta.
    StudentPlan.objects.filter(organization_id__isnull=True).update(
        organization_id=Subquery(
            Plan.objects.order_by()
            .filter(pk=OuterRef('plan_id'))
            .values('organization_id')[:1]
        )
    )

    # Fallback defensivo. `Plan.organization` es NOT NULL desde 0013 y `StudentPlan.plan`
    # también, así que no debería alcanzar ninguna fila. Se deja porque la columna va a
    # quedar NOT NULL y PROTECT, pero NO en silencio: derivar del usuario puede MOVER DE
    # TENANT una membresía —el alumno pudo cambiarse de organización y la membresía sigue
    # siendo de quien la vendió—, así que si alguna vez corre tiene que quedar registrado
    # qué filas tocó.
    fallback_ids = list(
        StudentPlan.objects.filter(organization_id__isnull=True)
        .values_list('id', flat=True)[:50]
    )
    if fallback_ids:
        print(
            '\n0030_studentplan_organization: ATENCIÓN — '
            f'{len(fallback_ids)} membresía(s) sin organización derivable de su plan; se '
            'resuelven por la organización ACTUAL del alumno, que puede no ser la que '
            f'vendió la membresía. Revisá estas filas: {fallback_ids}.'
        )
        StudentPlan.objects.filter(organization_id__isnull=True).update(
            organization_id=Subquery(
                User.objects.order_by()
                .filter(pk=OuterRef('user_id'))
                .values('organization_id')[:1]
            )
        )

    orphans = list(
        StudentPlan.objects.filter(organization_id__isnull=True)
        .values_list('id', flat=True)[:50]
    )
    if orphans:
        raise DataInconsistency(
            'No se puede aplicar 0030_studentplan_organization: quedaron membresías sin '
            'organización resoluble (ni por su plan ni por su alumno). Asignales una '
            'organización a mano antes de migrar. Ids: '
            f'{", ".join(str(pk) for pk in orphans)}.'
        )


def unapply_backfill(apps, schema_editor):
    """No-op: al revertir, el `RemoveField` se lleva la columna entera. No hay estado
    previo que restaurar —los valores se derivan de `plan.organization`, que sigue ahí—."""


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0029_plan_studentplan_consumptionlog_branch'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentplan',
            name='organization',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='student_plans',
                to='core.organization',
            ),
        ),
        migrations.RunPython(backfill_organization, unapply_backfill),
        migrations.AlterField(
            model_name='studentplan',
            name='organization',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='student_plans',
                to='core.organization',
            ),
        ),
    ]
