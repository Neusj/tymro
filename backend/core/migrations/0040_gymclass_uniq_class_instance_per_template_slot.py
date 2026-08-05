from collections import defaultdict

from django.db import migrations, models


def resolve_duplicate_template_instances(apps, schema_editor):
    """Deja UNA sola `GymClass` por (plantilla, horario) antes de que entre el constraint.

    Por qué existe esta migración de datos y no solo el `AddConstraint`: Railway corre
    `manage.py migrate` PRE-DEPLOY contra la base de producción, con datos reales que
    pueden contener duplicados creados por la race que este cambio viene a cerrar
    (check-then-create en `generate_instances_for_template_range`). Un `AddConstraint`
    solo reventaría el deploy con `UniqueViolation` y dejaría al cliente sin servicio, así
    que el orden de operaciones es OBLIGATORIAMENTE: primero limpiar, después restringir.

    Criterio de qué fila se conserva por grupo:

    1. La que tenga MÁS historia (inscripciones + logs de consumo). Es la que los alumnos
       y el gimnasio "ven": borrarla haría desaparecer reservas que sí existen.
    2. A igualdad de historia (incluido el caso de las dos en cero), la MÁS ANTIGUA
       (menor `id`) — la que el primer escritor de la carrera creó.

    Las perdedoras se borran EXCLUSIVAMENTE por `_delete_class_refunding_consumption`
    (`core/services/recurrence.py`), que primero corre `revert_consumption_for_class` y
    después `delete()`. NUNCA un `.delete()` directo: `ConsumptionLog.class_instance` es
    CASCADE, así que borrar a secas se lleva los logs sin decrementar
    `StudentPlan.classes_used` y deja saldo fantasma (el consumo doble de la race quedaría
    cobrado para siempre — justo el daño que este cambio repara).

    TENSIÓN MODELOS HISTÓRICOS vs MODELOS VIVOS, y por qué esta forma es segura:
    `RunPython` recibe modelos históricos (`apps.get_model`), que no tienen managers ni
    métodos custom, y el reverso de consumo necesita el servicio VIVO. Entonces:

    * La DETECCIÓN y la elección de la fila a conservar usan SOLO modelos históricos.
    * El servicio vivo se importa DENTRO de la rama que ya sabe que hay duplicados. En una
      base sana —cualquier base nueva, y la de producción una vez limpia— el `SELECT` de
      detección no devuelve nada, la función es un no-op y el import vivo NUNCA se
      ejecuta. O sea: el escenario clásico de drift (correr esta migración vieja contra un
      `models.py` que ya avanzó varias migraciones) no toca código vivo, porque no hay
      filas que resolver. El riesgo queda acotado a la ÚNICA corrida que sí encuentra
      duplicados, que es la de este deploy, donde código y esquema van juntos.

    Barre TODAS las organizaciones sin filtrar por `organization_id`: es mantenimiento de
    datos offline, no una query de runtime, y el aislamiento multi-tenant no aplica acá
    (además el grupo entero cuelga de una misma plantilla, que pertenece a una sola
    organización, así que nunca se mezclan tenants dentro de un grupo).
    """
    GymClass = apps.get_model('core', 'GymClass')
    Enrollment = apps.get_model('core', 'Enrollment')
    ConsumptionLog = apps.get_model('core', 'ConsumptionLog')

    # `.order_by()` limpia el `ordering = ['-start_datetime']` del Meta: con un ordering
    # por default, Django lo mete en el GROUP BY del `values().annotate()` y el conteo
    # puede salir mal agrupado.
    duplicate_groups = (
        GymClass.objects.filter(class_template__isnull=False)
        .values('class_template_id', 'start_datetime')
        .order_by()
        .annotate(total=models.Count('id'))
        .filter(total__gt=1)
    )

    slots = [(row['class_template_id'], row['start_datetime']) for row in duplicate_groups]
    if not slots:
        # Camino normal (base nueva o base ya limpia): sin duplicados no se importa ni se
        # ejecuta nada del código vivo. Ver la nota de drift en el docstring.
        return

    # Imports diferidos a propósito: solo llega acá la corrida que de verdad tiene que
    # reparar datos.
    from core.models import GymClass as LiveGymClass
    from core.services.recurrence import _delete_class_refunding_consumption

    for class_template_id, start_datetime in slots:
        candidate_ids = list(
            GymClass.objects.filter(
                class_template_id=class_template_id,
                start_datetime=start_datetime,
            )
            .order_by('id')
            .values_list('id', flat=True)
        )
        if len(candidate_ids) < 2:
            continue

        history = defaultdict(int)
        for gym_class_id in Enrollment.objects.filter(gym_class_id__in=candidate_ids).values_list(
            'gym_class_id', flat=True
        ):
            history[gym_class_id] += 1
        for gym_class_id in ConsumptionLog.objects.filter(class_instance_id__in=candidate_ids).values_list(
            'class_instance_id', flat=True
        ):
            history[gym_class_id] += 1

        # Más historia primero; a igualdad, el id más chico (la instancia más antigua).
        keeper_id = min(candidate_ids, key=lambda gym_class_id: (-history[gym_class_id], gym_class_id))

        for gym_class in LiveGymClass.objects.filter(
            id__in=[gym_class_id for gym_class_id in candidate_ids if gym_class_id != keeper_id]
        ):
            # Se re-lee con el modelo VIVO porque el servicio consulta
            # `ConsumptionLog.objects.filter(class_instance=gym_class)`: una instancia del
            # modelo histórico no es del mismo `class` que espera esa FK.
            _delete_class_refunding_consumption(gym_class)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_organization_class_pruning_grace_days'),
    ]

    operations = [
        # ORDEN NO NEGOCIABLE: limpiar duplicados y DESPUÉS restringir. Al revés, el
        # `AddConstraint` falla el `migrate` pre-deploy en producción.
        # `reverse_code=noop`: desaplicar no puede "des-borrar" las instancias duplicadas
        # (ni querría: eran el bug). El `AddConstraint` sí tiene reverso automático.
        migrations.RunPython(resolve_duplicate_template_instances, migrations.RunPython.noop),
        # La constraint va por EXPRESIONES (`F`) y no por `fields=[...]` a propósito: con
        # `fields`, DRF 3.15 le inyecta un `UniqueTogetherValidator` a `GymClassSerializer`
        # y vuelve OBLIGATORIO `class_template` en `POST /api/classes/`, rompiendo la
        # creación de clases sueltas. El detalle completo está en `GymClass.Meta`.
        migrations.AddConstraint(
            model_name='gymclass',
            constraint=models.UniqueConstraint(
                models.F('class_template'),
                models.F('start_datetime'),
                name='uniq_class_instance_per_template_slot',
            ),
        ),
    ]
