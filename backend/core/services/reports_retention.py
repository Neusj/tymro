"""Reporte de VENCIMIENTOS Y RENOVACIONES — retención (P3.4 · parte 2, pieza 1).

Responde tres números sobre el período: cuántas membresías VENCIERON, cuántas se RENOVARON y
cuántas se PERDIERON. Más un KPI mirando hacia adelante (cuántas están por vencer) y el corte
por plan de catálogo, que es el accionable ("qué plan no retiene").

TODAS LAS DEFINICIONES DE ESTE MÓDULO, EXPLÍCITAS
=================================================

**1. EL ANCLA TEMPORAL ES `StudentPlan.end_date`, NO `is_active`.**
"Vence en el período" es `end_date` dentro de `[date_from, date_to]`. `is_active` NO participa
en NINGUNA parte de este reporte, y no es un olvido: ese flag tiene semántica DISTINTA según
quién escribió la fila. `activate_student_plan` lo deja en `True` para siempre (para él
significa "no fue reemplazada"), mientras que el importador lo deriva de `end_date >= hoy`
(para él significa "está vigente"). Filtrar por `is_active=True` traería solo las filas del
importador vigentes hoy; filtrar por `is_active=False` traería un subconjunto arbitrario de las
vencidas. `describe_student_plan` (services/plans.py) ya fijó el orden correcto —LAS FECHAS
DECIDEN PRIMERO— y este reporte usa únicamente la fecha.

Ventaja lateral: `end_date` es un `DateField`, no un `DateTimeField`. A diferencia de la parte
1 (que compara con `__date__gte/__date__lte` para que Postgres convierta a `America/Santiago`),
acá la comparación es directa y no hay huso horario que pueda correr un vencimiento de día.

**2. "RENOVADA" = EXISTE OTRA INSTANCIA DEL MISMO LINAJE QUE EXTIENDE LA COBERTURA.**
El linaje es el que ya definió `plans._repoint_recurring_series_to_renewed_membership`: MISMO
`plan_id` de catálogo + MISMO `user_id` + MISMA `organization_id`. La organización NO es
redundante con el plan: `StudentPlan.organization` es una COPIA hecha al vender y nada
revalida las ventas históricas si el plan se mueve de tenant, así que dos instancias del mismo
`Plan` pueden tener organizaciones distintas (ver el comentario de la Regla 2 en esa función).
Acá el filtro por organización sale del `scope`, así que ese caso queda cubierto por
construcción.

El predicado de "posterior" es `nueva.end_date > vieja.end_date`, y NO
`nueva.start_date > vieja.end_date`. El motivo es la RENOVACIÓN ANTICIPADA: la vieja vence
mañana y la nueva ya está creada arrancando mañana (o incluso hoy, solapando un día, que es lo
que pasa cuando el admin renueva el mismo día del vencimiento con `start_date = hoy`). Ese
alumno SÍ se retuvo; exigir que la nueva empiece DESPUÉS del vencimiento lo contaría como
perdido, o sea el reporte mentiría justo en el caso del alumno más fiel. Con "la cobertura del
linaje se extiende más allá de la fecha que venció" entran los tres casos —anticipada, del
mismo día y tardía— y ninguna fila puede ser su propia renovación.

**3. HAY UNA VENTANA DE GRACIA (`RENEWAL_GRACE_DAYS`), Y NO ES CAPRICHO.**
La instancia nueva además tiene que empezar dentro de `end_date + RENEWAL_GRACE_DAYS`. Sin ese
tope, un alumno que vuelve en diciembre a comprar el mismo plan que le venció en enero
convertiría ese enero en "renovado" once meses después: el número de un período CERRADO
cambiaría hacia atrás cada vez que alguien reaparece, que es exactamente el modo de fallo que
`reports_revenue` evita al contar el bruto por `collected_at`. Volver a los seis meses es una
RECONQUISTA, otra pregunta de negocio. Con la gracia, pasados `end_date + gracia` días el
veredicto de esa membresía es definitivo y nunca más se mueve.

La contrapartida se publica en vez de esconderse: `totals.pending_grace` cuenta las
membresías cuyo veredicto TODAVÍA puede cambiar (la gracia sigue abierta hoy). Un "perdidas:
40" recién vencidas ayer no es una pérdida consumada, y sin ese contador el administrador no
tiene forma de saberlo.

**4. LA RENOVACIÓN SE IMPUTA AL BUCKET DEL VENCIMIENTO, NUNCA AL DE LA ACTIVACIÓN NUEVA.**
El gráfico es "vencidas vs renovadas en el tiempo" y las dos series tienen que ser comparables
PUNTO A PUNTO: en cada bucket, `renewed <= expired` y la división de las dos da la tasa de ese
bucket. Si las renovadas se imputaran a la fecha de la compra nueva, un bucket podría tener
más renovaciones que vencimientos (varios vencimientos de días distintos renovados el mismo
día), y las renovaciones anticipadas o dentro de la gracia caerían FUERA del período —el
gráfico mostraría vencimientos sin su renovación al lado, sugiriendo una fuga que no existe—.
Con el ancla en el vencimiento, `renewed` es siempre un SUBCONJUNTO de `expired` en el mismo
punto.

**5. EL KPI "POR VENCER" ESTÁ ANCLADO EN HOY Y LO DECLARA.**
`upcoming` mira los próximos `UPCOMING_WINDOW_DAYS` días DESDE HOY y NO depende del período
del filtro. Publica `as_of` (el hoy con el que se calculó), su propio rango y el booleano
`overlaps_period`. Se publica SIEMPRE, también cuando el reporte es de un período pasado: un
KPI que desaparece según el filtro es una función que el administrador cree perdida, y uno que
se anclara en `date_to` sería peor —"por vencer" respecto de una fecha pasada ya se resolvió, y
esas membresías ya están contadas en `expired`/`renewed`—. Con `overlaps_period=false` el
front puede rotularlo "no corresponde al período consultado" sin que el dato se pierda.

`upcoming` además descuenta las que YA tienen renovación cargada (`already_renewed`, el caso de
la renovación anticipada) y publica `at_risk`: son las que hay que ir a buscar.

⚠️ **6. FILTRO POR SUCURSAL: LA SEDE DE ACTIVACIÓN **MÁS** LOS PLANES GENUINAMENTE GLOBALES.**
Hay DOS columnas de sede en juego y la diferencia entre ellas es la decisión entera:

* **`StudentPlan.branch` = dónde se ACTIVÓ la membresía.** Es un registro histórico y su NULL
  está **SOBRECARGADO**: significa (a) el plan era global al momento de vender —los dos
  escritores, `activate_student_plan` y el importador, copian `plan.branch`— **O** (b) la
  sucursal se borró después, porque esa FK es **`SET_NULL`**. El comentario del campo en
  `models.py` lo dice literal: «acá NULL significa "sin sede registrada", no "todas las
  sedes"». Ese mismo comentario nombra a `plan.branch` como «la fuente de verdad del alcance».
* **`Plan.branch` = el ALCANCE del plan.** Su NULL significa "vale en toda la organización" sin
  ambigüedad, y eso está garantizado por el esquema: es **`RESTRICT`** justamente para que
  borrar una sucursal no pueda convertir un plan exclusivo en global (su comentario en
  `models.py` nombra esa inversión de semántica como el motivo de no usar `SET_NULL`). Es la
  misma columna contra la que el motor de reservas evalúa la cobertura
  (`plan_covers_branch`, reservations.py).

Filtrar `branch=scope.branch` a secas haría DESAPARECER del reporte todas las membresías
vendidas con planes globales. En un gimnasio que solo vende planes globales —la
configuración más común— el reporte por sede daría CERO vencimientos y CERO renovaciones, y la
tasa se calcularía sobre un universo recortado en silencio. Es el mismo modo de fallo que el
`ManualPayment.method=''` de la parte 1: plata (acá, gente) real que un filtro borraba sin
avisar.

Pero rescatar esas filas con `branch IS NULL` a secas es el error SIMÉTRICO, y es el que este
módulo tuvo hasta que lo encontró la revisión de seguridad: como ese NULL está sobrecargado,
una membresía de **Sede Norte cuya sucursal fue borrada** aparecería en el reporte de TODAS las
sedes y encima rotulada como "plan global". Es un vencimiento imputado a una sede donde no
ocurrió. El camino es alcanzable dentro del tenant y no hay guarda que lo corte: se le cambia
la sede a un `Plan` y después se borra la sucursal que quedó huérfana (el `_cascade_blocker` de
`views.py` bloquea el borrado por clases, series, feriados, reglas de pago, planes exclusivos y
cuentas de cobro, pero **no** por `StudentPlan.branch`).

Por eso el universo, con `scope.branch` puesto, es:

    branch = esa sede    OR    (branch IS NULL  AND  plan.branch IS NULL)

o sea **"se activó en esta sede"** o **"es de un plan genuinamente global y no tiene sede
estampada"**. Las dos ramas son disjuntas por construcción (una mira `branch = X`, la otra
`branch IS NULL`), así que ninguna fila se cuenta dos veces dentro de una misma vista.

Consecuencias declaradas, las tres:

1. **Las membresías de plan global aparecen en TODAS las vistas por sede, así que los reportes
   por sede NO suman el total de la organización.** Es un solape DECLARADO —
   `totals.global_plan_memberships` publica cuántas filas del conteo son de un plan global— y no
   un hueco mudo: entre las dos lecturas honestas es la única que no le esconde al administrador
   la mitad de su cartera.
2. **Una membresía cuya sucursal fue borrada, sobre un plan EXCLUSIVO, desaparece de TODA vista
   por sede y solo se ve en la vista de la organización.** Es la lectura conservadora: el dato de
   dónde ocurrió ese vencimiento se destruyó con la sucursal, y no hay ninguna sede a la que
   imputarlo sin inventar. Se prefiere que falte en un corte antes que aparecer en todos.
3. **El alcance se lee del plan HOY, no del que tenía al vender.** Si un plan exclusivo se pasa a
   global, sus membresías históricas sin sede estampada empiezan a aparecer en todas las vistas
   por sede (y al revés). Es deliberado: `plan.branch` es la única de las dos columnas cuya
   semántica el esquema garantiza, y es la misma que decide hoy dónde puede reservar ese alumno.
   Las que sí tienen sede estampada no se mueven: `branch = X` es un hecho y manda sobre el
   alcance actual del plan.

**7. NUMERADOR Y DENOMINADOR VIVEN EN EL MISMO UNIVERSO, POR CONSTRUCCIÓN.**
El filtro (período + sede + plan) selecciona el DENOMINADOR: las membresías que vencieron. El
numerador NO es una segunda consulta filtrada igual, es un PREDICADO que se evalúa sobre esas
mismas filas. La búsqueda de la instancia sucesora se hace solo por organización y linaje: NO
se le vuelve a aplicar el filtro de sede ni el de plan. Si se le aplicara, una renovación real
podría quedar afuera —una sede borrada dejó la fila nueva en NULL, o el `switched_plan` es por
definición de otro plan— y una renovación existente se contaría como pérdida. La tasa no puede
tener numerador y denominador seleccionados por criterios distintos.

LÍMITES CONOCIDOS (no son bugs: son consecuencias del criterio pedido)
=====================================================================
* **Renovar con OTRO plan del catálogo NO es una renovación.** El linaje es `plan_id`, así que
  el alumno que dejó el pack de 8 y se pasó al mensual ilimitado cuenta como PERDIDO en
  `renewal_rate`. Es la definición pedida y no se toca. Lo que sí se hace es MEDIRLO en vez de
  dejarlo invisible: `totals.switched_plan` cuenta esas filas y `totals.retention_rate` es la
  tasa de personas que siguieron entrenando con CUALQUIER plan. Son dos números con nombres
  distintos y `renewal_rate` nunca mezcla linajes.
* **`expired` cuenta MEMBRESÍAS, no personas.** Un alumno con dos membresías que vencen (dos
  disciplinas, que 7.1 permite explícitamente) aporta dos al denominador. Es lo que dice el
  título del reporte ("cuántas membresías vencen"), y también lo que hace que la tasa sea
  comparable con `by_plan`.
* **Los planes de tipo `trial` y `giftcard` cuentan como cualquier otro vencimiento.** Casi
  nunca se renuevan con el mismo plan, así que hunden la tasa. No se excluyen porque eso sería
  inventar una regla que nadie pidió; `by_plan` los deja a la vista con nombre y apellido.
* **Si el período incluye fechas FUTURAS, `expired` incluye vencimientos que todavía no
  ocurrieron.** El ancla es `end_date` dentro del rango y el rango lo elige el administrador.
  Esas filas caen enteras en `pending_grace` (su veredicto no puede estar cerrado), así que el
  payload alcanza para distinguirlas.
* **Una membresía dada de baja a mano dentro de su ventana (`is_active=False` con `end_date`
  futuro) igual cuenta como vencimiento el día de su `end_date`.** No hay columna con la fecha
  de la baja, así que la base no permite afirmar otra cosa (ver la decisión 1).

TODO SALE DE NUESTRA BASE y todo está scopeado por `scope.organization_id`, que es la
organización DEL ACTOR (la estampa `views_reports._report_scope`, nunca el request). La
organización no es un parámetro de este reporte.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ..models import StudentPlan
# `rate_pct` y `points_delta` viven en `reports_base` y NO acá: el reporte de conversión de
# trials (`reports_trial`) usa exactamente las mismas dos funciones, y una copia por módulo es
# la forma en que dos mitades de la misma feature divergen sin que nada lo detecte.
from .reports_base import bucket_key, bucket_keys, pct_delta, points_delta, rate_pct

# Días después del vencimiento en que una instancia nueva del mismo linaje todavía cuenta como
# RENOVACIÓN. Ver la decisión 3 del docstring del módulo. Vive como global de módulo y no como
# default de parámetro para que un test lo pueda mover con
# `monkeypatch.setattr(reports_retention, 'RENEWAL_GRACE_DAYS', N)` sin fabricar meses de
# historia, igual que `reports_revenue_detail.MAX_ROWS`.
RENEWAL_GRACE_DAYS = 30

# Ventana del KPI forward-looking "por vencer", en días desde HOY. Ver la decisión 5.
UPCOMING_WINDOW_DAYS = 30

# Resultado del predicado de renovación. Internos: al cable van los contadores, no estos
# strings.
_RENEWED_LINEAGE = 'lineage'      # misma instancia de plan: RENOVACIÓN
_RENEWED_OTHER_PLAN = 'other'     # se pasó a otro plan del catálogo: retenido, no renovado

#: Etiqueta del grupo de `by_plan` cuando el plan de catálogo no tiene nombre.
#: NO cubre un `plan__name` NULL: `StudentPlan.plan` es una FK NOT NULL (el JOIN es INNER) y
#: `Plan.name` no es nullable, así que ese caso no existe. Cubre el nombre VACÍO (`''`), que la
#: API impide pero la base permite —`CharField` sin `blank=True` lo valida en `full_clean()`, no
#: en el esquema—. Se conserva porque la alternativa es una celda vacía en la única columna que
#: identifica el grupo, indistinguible de un dato que se perdió en el camino.
UNKNOWN_PLAN_LABEL = 'Plan sin nombre'


# --------------------------------------------------------------------------------------
# Las dos consultas del cálculo. Son DOS y no una por fila: el rango puede ser de 731 días
# (`MAX_PERIOD_DAYS`) y esto corre en una request sincrónica de gunicorn con `--timeout 30`.
# --------------------------------------------------------------------------------------

def _branch_universe(queryset, branch):
    """Aplica el filtro de sede: esa sede MÁS los planes genuinamente globales sin sede.

    ⚠️ LAS DOS "SIMPLIFICACIONES" DE ESTA LÍNEA ESTÁN MAL, CADA UNA POR SU LADO (decisión 6
    del docstring del módulo, que hay que leer antes de tocar esto):

    * `filter(branch=branch)` a secas borra del reporte —y de la tasa— todas las membresías
      vendidas con planes GLOBALES, que en la mayoría de los gimnasios son la cartera
      completa. El reporte por sede daría cero.
    * `Q(branch=branch) | Q(branch__isnull=True)` a secas mete en TODAS las sedes a las
      membresías que quedaron sin sede porque la sucursal se BORRÓ (`StudentPlan.branch` es
      `SET_NULL`), imputando un vencimiento a una sede donde no ocurrió. Este era el bug.

    El desempate lo da `plan.branch`, la única de las dos columnas cuya semántica garantiza el
    esquema: es `RESTRICT` precisamente para que su NULL signifique "todas las sedes" y no
    pueda volverse NULL por un borrado. Así que "global" se le pregunta al PLAN
    (`plan__branch__isnull=True`) y "sin sede estampada" a la membresía
    (`branch__isnull=True`); hacen falta las dos.

    `branch` ya vino verificada como de esta organización (`views_reports._scoped_id`), así
    que acá se aplica y no se valida de nuevo.
    """
    if branch is None:
        return queryset
    return queryset.filter(
        Q(branch=branch)
        # `plan__branch` cuelga de una FK NOT NULL (`StudentPlan.plan`), así que el JOIN es
        # INNER y no puede perder filas.
        | (Q(branch__isnull=True) & Q(plan__branch__isnull=True))
    )


def _expiring_rows(*, organization_id, branch, plan, date_from, date_to):
    """Membresías cuyo `end_date` cae en el rango. DENOMINADOR del reporte.

    `.order_by()` descarta el `Meta.ordering = ['-start_date']` del modelo: el resultado se
    agrega en Python por bucket y por plan, así que el ORDER BY solo costaría un sort de
    miles de filas que nadie mira. Mismo criterio (y misma trampa evitada) que
    `reports_revenue._by_bucket`.
    """
    queryset = StudentPlan.objects.filter(
        organization_id=organization_id,
        # `end_date` es un DateField: comparación directa, sin `__date` y sin conversión de
        # huso. Ver la decisión 1.
        end_date__gte=date_from,
        end_date__lte=date_to,
    )
    queryset = _branch_universe(queryset, branch)
    if plan is not None:
        # Filtra el DENOMINADOR (qué vencimientos se miran). La búsqueda de la instancia
        # sucesora NO se filtra por plan: ver la decisión 7.
        queryset = queryset.filter(plan_id=plan.id)
    return list(
        # `plan__branch_id` y NO `branch_id` es lo que decide si esta membresía es GLOBAL: el
        # NULL de `StudentPlan.branch` está sobrecargado (sede borrada) y el de `Plan.branch`
        # no. Ver la decisión 6. Se traen las dos porque el filtro de universo usa ambas.
        queryset.values('id', 'user_id', 'plan_id', 'plan__name', 'end_date', 'branch_id',
                        'plan__branch_id')
        .order_by()
    )


def _candidates_by_user(*, organization_id, earliest_expiry, latest_deadline):
    """`{user_id: [filas candidatas a ser la renovación]}`, en UNA consulta.

    Candidata = cualquier membresía de ESTA organización que pueda extender el linaje de
    alguno de los vencimientos: `end_date` posterior al vencimiento más temprano del lote y
    `start_date` dentro de la gracia del más tardío. Los dos límites son los más laxos
    posibles sobre el lote completo; el predicado exacto por fila lo aplica `_renewal_kind`.

    NO se agrega un `user_id__in=[...]`/`plan_id__in=[...]` con los ids del lote: son miles
    de ids en un rango de dos años y el `IN` gigante es más caro que el rango de fechas, que
    además acota el resultado al mismo orden de magnitud. El diccionario por alumno hace el
    resto del filtrado en memoria.

    ⚠️ NO se filtra por sede ni por plan (decisión 7) ni por `is_active` (decisión 1): esto
    responde "¿existe la instancia que continúa?", y cualquier filtro extra acá convierte
    renovaciones reales en pérdidas.
    """
    rows = (
        StudentPlan.objects.filter(
            organization_id=organization_id,
            end_date__gt=earliest_expiry,
            start_date__lte=latest_deadline,
        )
        .values('id', 'user_id', 'plan_id', 'start_date', 'end_date')
        .order_by()
    )
    index = {}
    for row in rows:
        index.setdefault(row['user_id'], []).append(row)
    return index


def _renewal_kind(row, candidates_by_user, grace_days):
    """`_RENEWED_LINEAGE`, `_RENEWED_OTHER_PLAN` o ``None`` para UNA membresía vencida.

    Un solo lugar donde vive el predicado: lo usan el período actual, el período de
    comparación y el KPI "por vencer". Si cada uno lo escribiera por su cuenta, el delta
    estaría comparando dos definiciones de renovación en vez de dos períodos (la lección de
    `reports_revenue._method_data`).
    """
    end_date = row['end_date']
    deadline = end_date + timedelta(days=grace_days)
    other_plan = False

    for candidate in candidates_by_user.get(row['user_id'], ()):
        # Una membresía no puede ser su propia renovación. `end_date > end_date` ya lo
        # excluiría; el chequeo de id es explícito para que quede dicho.
        if candidate['id'] == row['id']:
            continue
        # Las DOS mitades del predicado de "posterior": extiende la cobertura (decisión 2) y
        # entra en la ventana de gracia (decisión 3).
        if candidate['end_date'] <= end_date or candidate['start_date'] > deadline:
            continue
        if candidate['plan_id'] == row['plan_id']:
            # El LINAJE GANA y corta: si el alumno compró el mismo plan y además otro, esto
            # es una renovación, no un cambio de plan.
            return _RENEWED_LINEAGE
        # Se anota y se SIGUE buscando: puede aparecer una candidata del mismo linaje más
        # adelante en la lista, y esa tiene prioridad.
        other_plan = True

    return _RENEWED_OTHER_PLAN if other_plan else None


# --------------------------------------------------------------------------------------
# Agregación. Los tres cortes (totales, serie, plan) salen del MISMO recorrido, como en
# `reports_occupancy.build_occupancy_report`: las reglas de borde se escriben una vez.
# --------------------------------------------------------------------------------------

def _empty_group():
    return {
        'expired': 0,
        'renewed': 0,
        'switched_plan': 0,
        'pending_grace': 0,
        'global_plan_memberships': 0,
    }


def _accumulate(group, *, kind, pending, is_global):
    group['expired'] += 1
    if kind == _RENEWED_LINEAGE:
        group['renewed'] += 1
    elif kind == _RENEWED_OTHER_PLAN:
        group['switched_plan'] += 1
    if pending:
        group['pending_grace'] += 1
    if is_global:
        group['global_plan_memberships'] += 1


def _group_payload(group):
    """Números publicados de un grupo (total, bucket o plan), con sus identidades.

    `lost = expired - renewed` SIEMPRE, y `churned = lost - switched_plan`: las restas se
    hacen acá una sola vez y sobre los enteros ya contados, así que las columnas del reporte
    cuadran entre sí y no puede pasar que el total diga una cosa y las filas de abajo sumen
    otra (mismo criterio que `reports_revenue._totals`).
    """
    expired = group['expired']
    renewed = group['renewed']
    switched = group['switched_plan']
    lost = expired - renewed
    return {
        'expired': expired,
        'renewed': renewed,
        'lost': lost,
        # ⊆ lost: se fue del linaje pero compró OTRO plan. Ver el límite conocido.
        'switched_plan': switched,
        # lost - switched_plan: no compró NADA en la ventana. La pérdida de verdad.
        'churned': lost - switched,
        # ⊆ churned (y por lo tanto ⊆ lost): el veredicto TODAVÍA puede cambiar —gracia
        # abierta hoy, o vencimiento que aún no ocurrió—. Solo se marca sobre las que no
        # compraron NADA: quien ya se pasó a otro plan tiene veredicto cerrado. Ver la
        # decisión 3.
        'pending_grace': group['pending_grace'],
        # ⊆ expired: cuántas de estas filas son de un plan cuyo alcance es TODA la
        # organización (`plan.branch IS NULL`, la fuente de verdad del alcance — NO el
        # `branch` de la membresía, que también es NULL cuando la sucursal se borró). Es lo
        # que hace que las vistas por sede no sumen el total de la organización: son las
        # filas que pueden aparecer en más de una vista (decisión 6).
        'global_plan_memberships': group['global_plan_memberships'],
        # La tasa PEDIDA: mismo linaje, nada más.
        'renewal_rate': rate_pct(renewed, expired),
        # Personas que siguieron entrenando con CUALQUIER plan. No reemplaza a la anterior:
        # existe para que el límite del linaje sea medible en vez de invisible.
        'retention_rate': rate_pct(renewed + switched, expired),
    }


def _tally(*, organization_id, branch, plan, date_from, date_to, grace_days, today):
    """`(payload de totales, filas ya clasificadas)` de un rango cualquiera.

    Factorizado porque lo llaman el período actual, el período de comparación y el KPI "por
    vencer": las tres lecturas tienen que usar el MISMO predicado de renovación y la MISMA
    definición de universo.
    """
    rows = _expiring_rows(
        organization_id=organization_id, branch=branch, plan=plan,
        date_from=date_from, date_to=date_to,
    )
    if not rows:
        # Sin filas no hay nada que buscar: se ahorra la segunda consulta (y `min()`/`max()`
        # sobre una lista vacía revientan).
        return _group_payload(_empty_group()), []

    end_dates = [row['end_date'] for row in rows]
    candidates = _candidates_by_user(
        organization_id=organization_id,
        earliest_expiry=min(end_dates),
        latest_deadline=max(end_dates) + timedelta(days=grace_days),
    )

    totals = _empty_group()
    classified = []
    for row in rows:
        kind = _renewal_kind(row, candidates, grace_days)
        # La gracia sigue abierta (o el vencimiento todavía no ocurrió): este veredicto no
        # está cerrado. Solo se marca sobre las NO renovadas: una renovada ya es un hecho.
        pending = kind is None and (row['end_date'] + timedelta(days=grace_days)) >= today
        # "Global" se le pregunta al PLAN y no a la membresía: `StudentPlan.branch` es NULL
        # tanto para un plan global como para una sucursal BORRADA (`SET_NULL`), y contar la
        # segunda como global rotularía mal exactamente el número que mide el solape entre
        # vistas por sede. `Plan.branch` es RESTRICT, así que su NULL solo puede significar
        # "toda la organización". Ver la decisión 6.
        is_global = row['plan__branch_id'] is None
        _accumulate(totals, kind=kind, pending=pending, is_global=is_global)
        classified.append((row, kind, pending, is_global))
    return _group_payload(totals), classified


def _upcoming(*, organization_id, branch, plan, grace_days, today, window_days):
    """KPI forward-looking: membresías que vencen en los próximos `window_days` DESDE HOY.

    ANCLADO EN HOY y NO en el período del filtro, y lo declara en el payload (`as_of`,
    `date_from`, `date_to`, `overlaps_period`). Ver la decisión 5 del docstring del módulo.

    `already_renewed` usa el MISMO predicado de linaje que el resto del reporte: es la
    renovación anticipada (la vieja vence en 10 días y la nueva ya está cargada). `at_risk`
    es la resta, o sea la lista que el gimnasio tiene que ir a buscar.
    """
    date_to = today + timedelta(days=max(window_days - 1, 0))
    totals, _rows = _tally(
        organization_id=organization_id, branch=branch, plan=plan,
        date_from=today, date_to=date_to, grace_days=grace_days, today=today,
    )
    expiring = totals['expired']
    already_renewed = totals['renewed']
    return {
        'as_of': today.isoformat(),
        'window_days': window_days,
        'date_from': today.isoformat(),
        'date_to': date_to.isoformat(),
        'expiring': expiring,
        'already_renewed': already_renewed,
        'at_risk': expiring - already_renewed,
    }


def build_retention_report(scope, *, plan=None):
    """Vencimientos y renovaciones del período de `scope`.

    `plan`, si viene, es un objeto `Plan` YA VERIFICADO como de la organización del actor (lo
    resuelve la view con `_scoped_id`, igual que `discipline` en el reporte de ocupación) y
    filtra el DENOMINADOR: qué vencimientos se miran. La búsqueda de la instancia sucesora
    nunca se filtra por plan —si lo hiciera, `switched_plan` sería imposible por
    construcción—.

    Todo el reporte sale filtrado por `scope.organization_id`, que es la organización DEL
    ACTOR: no hay forma de pedir la retención de otro gimnasio porque la organización no
    viaja en el request.
    """
    grace_days = RENEWAL_GRACE_DAYS
    # "Hoy" es el día del gimnasio (`America/Santiago`), no el día UTC del servidor: con
    # `date.today()` la gracia y el KPI "por vencer" se adelantarían un día durante las
    # últimas horas de cada jornada. Mismo criterio que `views_reports._report_scope`.
    today = timezone.localdate()

    totals, classified = _tally(
        organization_id=scope.organization_id, branch=scope.branch, plan=plan,
        date_from=scope.date_from, date_to=scope.date_to,
        grace_days=grace_days, today=today,
    )

    # El período anterior se calcula con LA MISMA función, el MISMO predicado y el MISMO
    # filtro: si se comparara contra otra definición de renovación, el delta mediría la
    # diferencia entre las dos definiciones y no el movimiento del negocio.
    previous_scope = scope.previous()
    previous_totals, _previous_rows = _tally(
        organization_id=previous_scope.organization_id, branch=previous_scope.branch,
        plan=plan, date_from=previous_scope.date_from, date_to=previous_scope.date_to,
        grace_days=grace_days, today=today,
    )

    # La serie nace COMPLETA y en cero: un bucket sin vencimientos es un dato (no venció
    # nada), no una ausencia de dato. Ver `reports_base.bucket_keys`.
    series = {key: _empty_group() for key in bucket_keys(scope)}
    by_plan = {}
    for row, kind, pending, is_global in classified:
        # Indexado directo y no `setdefault`: la clave SIEMPRE está porque `end_date` cae en
        # el rango del scope por el filtro de la consulta y es un `date` puro (sin huso que
        # pueda correrlo). Un KeyError acá sería un error real de aritmética de buckets y
        # tiene que verse, no rellenarse.
        _accumulate(series[bucket_key(row['end_date'], scope.granularity)],
                    kind=kind, pending=pending, is_global=is_global)
        # La clave es (id, nombre) por el mismo motivo que en `reports_occupancy`: si el
        # nombre falta, el grupo conserva su identidad por id.
        plan_key = (row['plan_id'], row['plan__name'] or UNKNOWN_PLAN_LABEL)
        _accumulate(by_plan.setdefault(plan_key, _empty_group()),
                    kind=kind, pending=pending, is_global=is_global)

    return {
        'period': scope.period_payload(),
        'filters': scope.filters_payload(
            plan_id=getattr(plan, 'id', None),
            plan_name=getattr(plan, 'name', None),
            # Los dos parámetros de negocio del cálculo viajan en la respuesta: el mismo
            # payload leído dentro de seis meses tiene que poder explicar sus propios
            # números, y estos dos son globales de módulo que un test puede mover.
            renewal_grace_days=grace_days,
            # Declarado acá también porque `upcoming` NO respeta el período del filtro y
            # esta es la fila donde el front busca "qué se aplicó".
            upcoming_window_days=UPCOMING_WINDOW_DAYS,
            # Ver la decisión 6: con sede puesta, el universo incluye las membresías de plan
            # global. El front puede rotular el solape sin adivinarlo.
            includes_global_plans=True,
        ),
        'totals': totals,
        'previous': {
            'period': previous_scope.period_payload(),
            'totals': previous_totals,
        },
        'comparison': {
            # PUNTOS PORCENTUALES, no variación porcentual de un porcentaje: ver
            # `reports_base.points_delta`.
            'renewal_rate_delta_pp': points_delta(
                totals['renewal_rate'], previous_totals['renewal_rate']),
            'retention_rate_delta_pp': points_delta(
                totals['retention_rate'], previous_totals['retention_rate']),
            'expired_delta': totals['expired'] - previous_totals['expired'],
            # Acá el % sí significa lo que parece (conteos, no tasas), así que se reusa el
            # helper de `reports_base`: `None` si el período anterior fue 0.
            'expired_delta_pct': pct_delta(totals['expired'], previous_totals['expired']),
            'renewed_delta': totals['renewed'] - previous_totals['renewed'],
            'renewed_delta_pct': pct_delta(totals['renewed'], previous_totals['renewed']),
        },
        'upcoming': dict(
            _upcoming(
                organization_id=scope.organization_id, branch=scope.branch, plan=plan,
                grace_days=grace_days, today=today, window_days=UPCOMING_WINDOW_DAYS,
            ),
            # El KPI está anclado en HOY: este booleano dice si esa ventana tiene algo que
            # ver con el período que el administrador está mirando. Se calcula acá, donde
            # están las dos fechas del scope, y no dentro de `_upcoming` (que no las conoce).
            overlaps_period=(today <= scope.date_to
                             and (today + timedelta(days=max(UPCOMING_WINDOW_DAYS - 1, 0)))
                             >= scope.date_from),
        ),
        # Orden por volumen y después por nombre, igual que `by_discipline` en ocupación: el
        # administrador entra a este corte para ver qué plan no retiene, y el que más vence
        # es el que más pesa en la tasa.
        'by_plan': [
            dict(_group_payload(group), plan_id=key[0], plan_name=key[1])
            for key, group in sorted(
                by_plan.items(), key=lambda item: (-item[1]['expired'], item[0][1]),
            )
        ],
        'series': [
            dict(_group_payload(series[key]), bucket=key)
            # Se recorre `bucket_keys` y no el dict: el orden del payload es el del período,
            # no el de inserción de las filas que llegaron.
            for key in bucket_keys(scope)
        ],
    }


def retention_export_spec(data):
    """`{'header', 'rows', 'total_row'}` para `reports_base.export_response`.

    Se exporta el corte por PLAN, que es el accionable ("qué plan no retiene"), más la fila
    de totales. La serie es un gráfico: una columna de 731 filas no se lee mejor en Excel que
    en pantalla (mismo criterio que `occupancy_export_spec`). El export sale de `data`, o sea
    del MISMO payload que devolvió el JSON, así que la planilla no puede divergir de lo que
    el administrador está mirando.

    La tasa va como número con un decimal y las que no son calculables (ningún vencimiento en
    ese plan, imposible en este bloque, pero la columna es la misma que la del total) salen
    como celda VACÍA y no como 0: un 0 % de renovación sobre cero vencimientos es una
    afirmación falsa escrita en un archivo que después alguien promedia.
    """
    header = ['Plan', 'Vencidas', 'Renovadas', 'Perdidas', 'Cambió de plan',
              'Sin recompra', 'Veredicto pendiente', 'Tasa renovación %',
              'Tasa retención %']

    def _cells(item):
        return [
            item['expired'], item['renewed'], item['lost'], item['switched_plan'],
            item['churned'], item['pending_grace'],
            '' if item['renewal_rate'] is None else item['renewal_rate'],
            '' if item['retention_rate'] is None else item['retention_rate'],
        ]

    rows = [[item['plan_name']] + _cells(item) for item in data['by_plan']]
    total_row = ['TOTAL'] + _cells(data['totals'])
    return {'header': header, 'rows': rows, 'total_row': total_row}
