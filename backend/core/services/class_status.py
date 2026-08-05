"""Consolidación del estado de las clases según el reloj: cierra lo que ya terminó, marca en
curso lo que arrancó, consolida asistencias y liquida el pago del profe.

Vivía como `_sync_class_statuses` en `core/views.py`, pensado como un helper de listado. Se
extrajo a un servicio porque tiene DOS llamadores con necesidades distintas y ninguno debería
depender del otro:

* el **request path** (`views.py`: dashboard, listados de clases y de inscripciones) lo corre
  de paso, acotado a lo que ese actor puede alcanzar (`_class_sync_scope(user)`);
* el **job diario** (`services/rolling_window.py`, fase 2) lo corre por organización ANTES de
  podar, para que la poda decida sobre estado consolidado y no dependa de que alguien haya
  abierto la app.

Es una función de ESCRITURA disfrazada de listado (ver el comentario del argumento), así que
el scoping es del llamador: acá no hay ni un default de queryset.
"""
from django.db import transaction

from ..models import GymClass
from .teacher_payments import calculate_teacher_payment


def sync_class_statuses(base_queryset):
    # El queryset es OBLIGATORIO a proposito: esta funcion ESCRIBE (status, is_active,
    # closed_at, Attendance y TeacherPaymentRecord). Con un default global, un call site
    # futuro que se olvide del argumento reintroduce en silencio la escritura sobre todas
    # las organizaciones. Usar `_class_sync_scope(user)`.
    queryset = base_queryset
    candidates = queryset.filter(status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS])
    for gym_class in candidates:
        # El flip de status y su TeacherPaymentRecord tienen que commitear JUNTOS: la poda
        # de `advance_class_windows` acepta `completed` sin pago, y entre un flip ya
        # commiteado y un TPR todavía en vuelo puede borrar la clase (liquidación perdida
        # + IntegrityError del INSERT huérfano). Atómico por clase, el FOR UPDATE de la
        # poda espera al commit completo y su re-check ya ve el TPR.
        with transaction.atomic():
            gym_class.refresh_status_from_schedule(save=True)
            if gym_class.status in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
                calculate_teacher_payment(gym_class)
