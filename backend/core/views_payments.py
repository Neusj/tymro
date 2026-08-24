"""APIViews de pagos (MercadoPago). Split de views.py por tamaño.
Todas respetan multitenancy: connect/account filtran por request.user.organization;
el callback resuelve la org por el state firmado (nunca por el Host)."""
import logging
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.shortcuts import get_object_or_404, redirect
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (Branch, PaymentAccount, PaymentTransaction, Plan, StudentPlan,
                     WebhookEvent)
from .serializers import (PaymentAccountSerializer, PaymentCheckoutRequestSerializer,
                          PaymentTransactionAdminSerializer,
                          PaymentTransactionStatusSerializer)
from .services import payments
from .services.providers import get_payment_provider
from .views import _acts_as_student, _is_gym_admin, _is_superadmin   # helpers de rol existentes

logger = logging.getLogger(__name__)


# Validación de FORMA del `branch_id`, con el MISMO campo que
# `ManualPaymentCreateSerializer.student_plan` (serializers.py:1860) — no un `int()` a mano:
#
# * `int()` acepta floats y bools EN SILENCIO (`int(7.9)` → 7, `int(True)` → 1), o sea el
#   cliente pide una sede y el servidor termina operando sobre OTRA (o sobre la sede 1). El
#   `IntegerField` de DRF los rechaza con 400.
# * `min_value=1`: el 0 y los negativos no son ids.
# * `max_value=2**63-1`: fuera del rango de bigint el `filter(id=...)` revienta en PostgreSQL
#   con un 500 que SQLite no reproduce, así que la suite no lo detectaría (misma lección que
#   `_as_id_list`, views.py:180-200).
_branch_id_field = serializers.IntegerField(min_value=1, max_value=2 ** 63 - 1)


def _branch_scope(user, raw_branch_id):
    """Sucursal sobre la que opera el endpoint, o ``None`` = cuenta PRINCIPAL de la org.

    Se llama SIEMPRE DESPUÉS de las guardas de rol y de organización (lección 8.3: la sede
    se resuelve al final, nunca antes de saber quién pregunta). El lookup intersecta
    `organization_id` del ACTOR —jamás una organización del payload—, así que una sede ajena
    es indistinguible de una inexistente.

    El 404 y no 403 es anti-oráculo: los ids de `Branch` son autoincrementales y
    adivinables, y un 403 confirmaría "esa sede existe, pero es de otro gimnasio",
    delatando la topología de sedes de otro tenant.
    """
    if raw_branch_id is None or raw_branch_id == '':
        return None
    try:
        branch_id = _branch_id_field.run_validation(raw_branch_id)
    except serializers.ValidationError as exc:
        # 400 y no 404: el valor es malformado, no "ajeno", y este camino no revela nada de
        # otro tenant. Se re-envuelve con la clave del campo para que el error del wire diga
        # QUÉ dato está mal, en vez de una lista suelta de mensajes.
        raise DRFValidationError({'branch_id': exc.detail})
    return get_object_or_404(Branch, id=branch_id, organization_id=user.organization_id)


def _main_account_is_connected(user):
    """¿La organización del actor tiene su cuenta PRINCIPAL conectada?

    `branch__isnull=True` + `status=connected` para el proveedor activo: una fila principal
    DESCONECTADA (tokens vaciados, conservada como histórico) no cobra nada, así que para
    esta pregunta es lo mismo que no tenerla."""
    return PaymentAccount.objects.filter(
        organization_id=user.organization_id, provider=settings.PAYMENTS_PROVIDER,
        branch__isnull=True, status=PaymentAccount.STATUS_CONNECTED).exists()


class PaymentConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            return Response({'detail': 'No tienes permisos para conectar pagos.'},
                            status=status.HTTP_403_FORBIDDEN)
        if user.organization_id is None:
            return Response({'detail': 'Usuario sin organización.'},
                            status=status.HTTP_400_BAD_REQUEST)
        # `branch_id` OPCIONAL: sin él se conecta la cuenta PRINCIPAL de la organización,
        # exactamente como hasta hoy. La sede viaja después dentro del state FIRMADO (ver
        # `_sign_state`), y `connect_callback` re-valida la pertenencia antes de escribir.
        branch = _branch_scope(user, request.data.get('branch_id'))
        if branch is not None and not _main_account_is_connected(user):
            # La cuenta principal es el PISO del modelo: es la que cobra por los planes
            # globales y por toda sede sin cuenta propia. Sin ella, un gimnasio que conectara
            # PRIMERO una sede tendría un MercadoPago funcionando y, al mismo tiempo, todo lo
            # demás resolviendo a `NotConnected` (`resolve_payment_account` cae a la principal
            # y no encuentra ninguna) → alumnos con "el gimnasio no tiene pagos habilitados"
            # en una organización recién conectada. Es la trampa de onboarding que se vio en
            # producción, y se cierra acá, en el único punto de entrada del flujo.
            #
            # 409 y no 400: la petición está bien formada, es el ESTADO del recurso el que no
            # la permite (mismo código que usa el checkout para `NotConnected`).
            #
            # Va DESPUÉS de rol + organización + pertenencia de la sede (orden 8.3): una sede
            # de otra organización sigue cortando con 404 antes de llegar acá, así que este
            # 409 no se convierte en un oráculo nuevo — solo lo ve quien ya probó que la sede
            # es suya.
            #
            # NO se replica en `connect_callback`: un state emitido ya pasó por esta guarda, y
            # re-chequear ahí rompería la reconexión de una sede si la principal se desconectó
            # en el medio. Desconectar la principal DESPUÉS de configurar sedes tampoco se
            # bloquea (queda como decisión de producto pendiente).
            return Response(
                {'detail': 'Conectá primero la cuenta principal del gimnasio antes de '
                           'configurar una cuenta por sucursal.'},
                status=status.HTTP_409_CONFLICT,
            )
        url = payments.build_connect_url(organization=user.organization, branch=branch)
        return Response({'authorization_url': url})


class PaymentOAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state')
        # Apex: destino de fallback cuando aún no sabemos la org (no hay subdominio al cual volver).
        apex = (getattr(settings, 'FRONTEND_URL', '') or settings.PAYMENTS_APEX_BASE_URL).rstrip('/')
        if not code or not state:
            return redirect(f'{apex}/ajustes/pagos?connected=0')
        # Resolver la org del state (el callback llega al apex; el tenant viaja en el state)
        # para redirigir al SUBDOMINIO del gym, así el gym_admin vuelve con su sesión intacta.
        try:
            organization = payments.organization_from_state(state)
        except payments.InvalidState:
            return redirect(f'{apex}/ajustes/pagos?connected=0&error=state')
        frontend = payments.frontend_base_for_organization(organization)
        try:
            payments.connect_callback(code=code, state=state)
        except payments.InvalidState:
            return redirect(f'{apex}/ajustes/pagos?connected=0&error=state')
        except Exception as exc:
            logger.warning('Fallo en callback OAuth de pagos (state válido, exchange falló): %s', exc)
            return redirect(f'{frontend}/ajustes/pagos?connected=0&error=exchange')
        return redirect(f'{frontend}/ajustes/pagos?connected=1')


def _scoped_account(user, branch):
    """Cuenta EXACTA que administran `account`/`disconnect`, o None si no existe.

    `branch=None` → `branch IS NULL` en el ORM, o sea la cuenta PRINCIPAL. El filtro por
    sede es lo que impide que estos endpoints toquen "alguna" cuenta de la organización: con
    el `.first()` sin acotar de antes, en cuanto una sede conecta su cuenta el orden queda
    indefinido y `disconnect` podía apagar la cuenta equivocada —dejando sin cobro a la sede
    que nadie tocó y creyendo el admin que desconectó la principal—."""
    return PaymentAccount.objects.filter(
        organization_id=user.organization_id, provider=settings.PAYMENTS_PROVIDER,
        branch=branch).first()


def _disconnected_payload(branch):
    return {'status': 'disconnected', 'provider': settings.PAYMENTS_PROVIDER,
            'branch': branch.id if branch is not None else None}


class PaymentAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            return Response({'detail': 'No tienes permisos.'}, status=status.HTTP_403_FORBIDDEN)
        # `?branch_id=` OPCIONAL: sin él se devuelve la cuenta PRINCIPAL (`branch IS NULL`),
        # que es lo que este endpoint devolvía cuando era la única que podía existir.
        branch = _branch_scope(user, request.query_params.get('branch_id'))
        account = _scoped_account(user, branch)
        if account is None:
            return Response(_disconnected_payload(branch))
        return Response(PaymentAccountSerializer(account).data)


class PaymentDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            return Response({'detail': 'No tienes permisos para desconectar pagos.'},
                            status=status.HTTP_403_FORBIDDEN)
        # Mismo scoping que PaymentAccountView: SIEMPRE por la org del actor, jamás por
        # un id de cuenta recibido en el payload. Así el gym_admin solo puede tocar sus
        # propias cuentas. `branch_id` elige CUÁL de ellas (sin él, la principal) y pasa por
        # la misma guarda de pertenencia con 404 anti-oráculo.
        branch = _branch_scope(user, request.data.get('branch_id'))
        account = _scoped_account(user, branch)
        if account is None:
            return Response(_disconnected_payload(branch))
        payments.disconnect_account(account)
        return Response(PaymentAccountSerializer(account).data)


class PaymentCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not _acts_as_student(user):
            return Response({'detail': 'Solo alumnos pueden pagar.'}, status=status.HTTP_403_FORBIDDEN)
        req = PaymentCheckoutRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        plan = target = None
        if req.validated_data.get('plan_id'):
            plan = get_object_or_404(Plan, id=req.validated_data['plan_id'],
                                     organization_id=user.organization_id,
                                     is_active=True, is_public=True)
        else:
            # Acotado tambien por la organizacion que vendio la membresia: `create_checkout`
            # ya lo rechaza, pero el scoping tiene que dar el 404 sin depender de esa red.
            # Por la COLUMNA `organization` y no por el join `plan__organization`, igual que
            # el resto de los lectores. OJO: `create_checkout` (services/payments.py) todavia
            # valida `sp.plan.organization_id`, o sea la red de atras sigue mirando el join.
            target = get_object_or_404(StudentPlan, id=req.validated_data['target_student_plan_id'],
                                       user=user,
                                       organization_id=user.organization_id)
        try:
            tx, url = payments.create_checkout(organization=user.organization, user=user,
                                               plan=plan, target_student_plan=target)
        except payments.NotConnected:
            return Response({'detail': 'El gimnasio no tiene pagos habilitados.'},
                            status=status.HTTP_409_CONFLICT)
        except payments.CheckoutError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'transaction_id': str(tx.id), 'redirect_url': url})


class PaymentTransactionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tx = get_object_or_404(PaymentTransaction, id=pk,
                               organization_id=request.user.organization_id, user=request.user)
        return Response(PaymentTransactionStatusSerializer(tx).data)


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []   # sin SessionAuth → sin CSRF

    def post(self, request):
        raw_body = request.body
        provider = get_payment_provider()   # settings.PAYMENTS_PROVIDER
        headers = {k[5:].replace('_', '-').lower(): v
                   for k, v in request.META.items() if k.startswith('HTTP_')}
        if not provider.verify_webhook(headers=headers, raw_body=raw_body):
            logger.warning('Webhook de pago con firma inválida (x-request-id=%s)',
                           headers.get('x-request-id'))
            return Response({'detail': 'firma inválida'}, status=status.HTTP_401_UNAUTHORIZED)

        env = provider.parse_webhook(headers=headers, raw_body=raw_body)
        WebhookEvent.objects.create(
            provider=provider.name, provider_payment_id=env.provider_payment_id,
            raw_body=raw_body.decode('utf-8', 'replace'),
            headers={'x-request-id': headers.get('x-request-id')},
        )
        if env.type != 'payment' or not env.provider_payment_id:
            return Response(status=status.HTTP_200_OK)   # ack, ignorar

        tx_id = request.GET.get('tx')
        if tx_id:
            try:
                payments.process_payment_notification(
                    tx_id=tx_id, provider_payment_id=env.provider_payment_id)
            except (payments.PaymentIntegrityError, ValueError, ValidationError,
                    IntegrityError):
                # No re-encolar: es una inconsistencia (incl. tx malformado), no un fallo transitorio.
                #
                # `IntegrityError` entra en la lista desde P3.4: el camino nuevo de devolución
                # también escribe `provider_payment_id`, así que un aviso re-apuntado a otra
                # transacción puede chocar contra `uniq_provider_payment` (provider,
                # provider_payment_id). El `atomic` de `apply_provider_payment` ya revirtió —la
                # fila no queda a medias—, pero sin atajarlo acá el webhook devolvía 500 y MP
                # reintentaba en bucle un aviso que nunca va a poder aplicarse.
                return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_200_OK)


class PaymentTransactionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class PaymentTransactionListView(ListAPIView):
    """Listado de solo lectura de las PaymentTransaction de la organización del
    gym_admin. Acceso EXCLUSIVO de gym_admin sobre su propia org: superadmin y el
    resto de roles reciben 403 (el superadmin no debe ver los pagos de todos los
    gimnasios). Paginado, orden por fecha desc, con filtros por estado y fecha."""
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentTransactionAdminSerializer
    pagination_class = PaymentTransactionPagination

    def get_queryset(self):
        user = self.request.user
        if not (_is_gym_admin(user) and user.organization_id):
            raise PermissionDenied('Solo el administrador del gimnasio puede ver las transacciones.')

        qs = (PaymentTransaction.objects
              .filter(organization_id=user.organization_id)
              # `branch` acompaña al resto: el serializer publica `branch_name`, y sin el
              # join cada fila de la página dispararía su propia query por la sucursal.
              .select_related('user', 'plan', 'student_plan', 'branch')
              # Espejo del `line_items` de PaymentTransactionAdminSerializer (#12): sin este
              # prefetch, cada fila de la página dispara su propia query sobre
              # `charge_line_items` al pedir el desglose.
              .prefetch_related('student_plan__charge_line_items')
              .order_by('-created_at', '-id'))

        status_param = self.request.query_params.get('status')
        if status_param:
            valid = {choice[0] for choice in PaymentTransaction.STATUS_CHOICES}
            if status_param not in valid:
                raise DRFValidationError({'status': 'Estado inválido.'})
            qs = qs.filter(status=status_param)

        def _parse_date(value, field):
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                raise DRFValidationError({field: 'Formato de fecha inválido (usa YYYY-MM-DD).'})

        date_from = self.request.query_params.get('date_from')
        if date_from:
            qs = qs.filter(created_at__date__gte=_parse_date(date_from, 'date_from'))
        date_to = self.request.query_params.get('date_to')
        if date_to:
            qs = qs.filter(created_at__date__lte=_parse_date(date_to, 'date_to'))
        return qs
