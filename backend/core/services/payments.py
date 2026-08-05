"""Orquestación de dominio de pagos. No sabe de HTTP ni de MercadoPago:
delega en get_payment_provider(). Aísla la lógica de negocio de las views.
"""
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core import signing
from django.db import transaction as db_transaction
from django.utils import timezone

from core.models import PaymentAccount, PaymentTransaction, Plan
from .providers import PaymentProviderError, get_payment_provider
from .providers.base import BackUrls, CheckoutItem, PaymentStatus
from .public_urls import organization_public_base_url

STATE_SALT = 'payments-oauth'
STATE_MAX_AGE = 600          # 10 minutos
REFRESH_MARGIN = timedelta(hours=24)


class InvalidState(Exception):
    """El parámetro state del callback OAuth no es válido/expiró."""


class CheckoutError(Exception):
    """No se puede iniciar el cobro."""


class NotConnected(CheckoutError):
    """La organización no tiene cuenta de pago conectada."""


class PaymentIntegrityError(Exception):
    """El pago no cuadra con la transacción (monto/collector) — posible forja."""


def _sign_state(organization_id, branch_id=None) -> str:
    # nonce derivado del org_id + timestamp implícito de signing (no usamos Math.random).
    #
    # La SUCURSAL viaja acá, FIRMADA, y no como query param del callback: es el dato que
    # decide a qué sede se le cuelga la cuenta de cobro, y el callback es `AllowAny` sin
    # sesión (llega desde MercadoPago). Suelto en la URL, cualquiera podría redirigir la
    # cuenta de una sede a otra —o a una sede ajena— con solo editar el link de vuelta.
    return signing.dumps({'org': organization_id, 'branch': branch_id}, salt=STATE_SALT)


def _load_state(state):
    """``(organization_id, branch_id)`` del state firmado. ``branch_id`` None = principal."""
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidState('state inválido o expirado') from exc
    # `.get` y no `data['branch']`: los states emitidos por el código anterior siguen en
    # vuelo hasta `STATE_MAX_AGE` (10 min) después del deploy y no traen la clave. Sin el
    # `.get`, un gym_admin que apretó "conectar" justo antes del deploy vería un KeyError
    # (500) al volver de MercadoPago. Sin clave = cuenta principal, que es lo que pidió.
    return data['org'], data.get('branch')


def build_connect_url(*, organization, branch=None) -> str:
    """URL de autorización de MercadoPago. ``branch`` None = conectar la cuenta PRINCIPAL.

    La pertenencia de ``branch`` a ``organization`` la valida el CALLER antes de llamar
    (lección 8.3) y se RE-valida en `connect_callback`, que es quien escribe la fila."""
    provider = get_payment_provider()
    state = _sign_state(organization.id, branch.id if branch is not None else None)
    return provider.get_authorization_url(state=state, redirect_uri=settings.MP_OAUTH_REDIRECT_URI)


def organization_from_state(state):
    """Valida el ``state`` firmado y devuelve la Organization que viaja en él.
    Levanta InvalidState si el state es inválido/expiró o la org ya no existe.
    Se usa en el callback OAuth para saber a qué subdominio volver (el callback
    llega al apex; el tenant no viaja en el host, solo en el state)."""
    from core.models import Organization
    org_id, _branch_id = _load_state(state)
    try:
        return Organization.objects.get(id=org_id)
    except Organization.DoesNotExist as exc:
        raise InvalidState('la organización del state no existe') from exc


def _apex_frontend_base() -> str:
    return (getattr(settings, 'FRONTEND_URL', '') or settings.PAYMENTS_APEX_BASE_URL).rstrip('/')


def frontend_base_for_organization(organization) -> str:
    """Base del frontend para volver al SUBDOMINIO del gym tras el callback OAuth.

    Antepone el subdominio de la organización al host de ``FRONTEND_URL`` preservando
    esquema y puerto (ej. ``https://tymroapp.com`` → ``https://<sub>.tymroapp.com``;
    ``http://localhost:5173`` → ``http://<sub>.localhost:5173``). Si la org no tiene
    subdominio, cae al apex (``FRONTEND_URL``). NO cambia el ``redirect_uri`` de OAuth
    ni la ``notification_url`` del webhook: solo el destino del redirect posterior."""
    apex = _apex_frontend_base()
    subdomain = (getattr(organization, 'subdomain', '') or '').strip().lower()
    if not subdomain:
        return apex
    parts = urlsplit(apex)
    host = parts.hostname or ''
    if not host or host.split('.')[0] == subdomain:
        return apex   # sin host utilizable o ya es el subdominio → no duplicar
    netloc = f'{subdomain}.{host}'
    if parts.port:
        netloc = f'{netloc}:{parts.port}'
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip('/'), '', ''))


def connect_callback(*, code, state) -> PaymentAccount:
    from core.models import Branch, Organization
    org_id, branch_id = _load_state(state)
    organization = Organization.objects.get(id=org_id)
    branch = None
    if branch_id is not None:
        # ESTA es la guarda del lado ESCRITOR, y no es redundante con la de la view: esta
        # función es el ÚNICO código de producción que crea filas de `PaymentAccount`, y
        # nada a nivel de modelo impide colgar una cuenta de una sede de OTRA organización
        # (la FK a Branch no sabe de la columna `organization`). Sin este `get` acotado, un
        # state con una sede ajena —firmado por un bug futuro, o por un caller nuevo que se
        # saltee la view— crearía la fila cross-tenant y el dinero de esa sede empezaría a
        # entrar en el MercadoPago de otro gimnasio. Se valida ANTES del `exchange_code`
        # para no quemar el código OAuth en un intento que igual va a fallar.
        try:
            branch = Branch.objects.get(id=branch_id, organization=organization)
        except Branch.DoesNotExist as exc:
            raise InvalidState('la sucursal del state no pertenece a la organización') from exc
    provider = get_payment_provider()
    tokens = provider.exchange_code(code=code, redirect_uri=settings.MP_OAUTH_REDIRECT_URI)
    now = timezone.now()
    account, _ = PaymentAccount.objects.update_or_create(
        # `branch` va en el LOOKUP y no en `defaults`: es parte de la identidad de la
        # cuenta. En el lookup, `branch=None` se traduce a `branch IS NULL`, o sea "la
        # cuenta PRINCIPAL". Fuera del lookup, el `get` interno matchearía TODAS las
        # cuentas de la organización y reconectar la principal reventaría con
        # `MultipleObjectsReturned` (500) en cuanto exista una sola cuenta de sede.
        organization=organization, branch=branch, provider=provider.name,
        defaults=dict(
            provider_user_id=tokens.provider_user_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            public_key=tokens.public_key,
            scope=tokens.scope,
            token_expires_at=now + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None,
            status=PaymentAccount.STATUS_CONNECTED,
            connected_at=now,
        ),
    )
    return account


def disconnect_account(account) -> PaymentAccount:
    """Desconecta la cuenta: la marca ``disconnected`` y borra los tokens OAuth cifrados.
    NO borra la fila: se conserva el histórico y la reconexión posterior vía el
    ``update_or_create`` de ``connect_callback`` vuelve a rellenar los tokens.
    El scoping por organización es responsabilidad de la view que obtiene ``account``."""
    account.status = PaymentAccount.STATUS_DISCONNECTED
    account.access_token = None
    account.refresh_token = None
    account.token_expires_at = None
    account.save(update_fields=['status', 'access_token', 'refresh_token',
                                'token_expires_at', 'updated_at'])
    return account


def get_valid_access_token(*, account) -> str:
    expiring = (account.token_expires_at is None
                or account.token_expires_at <= timezone.now() + REFRESH_MARGIN)
    if not expiring:
        return account.access_token
    provider = get_payment_provider(account.provider)
    try:
        tokens = provider.refresh_tokens(refresh_token=account.refresh_token)
    except PaymentProviderError:
        account.status = PaymentAccount.STATUS_DISCONNECTED
        account.save(update_fields=['status', 'updated_at'])
        raise
    account.access_token = tokens.access_token
    account.refresh_token = tokens.refresh_token
    if tokens.expires_in:
        account.token_expires_at = timezone.now() + timedelta(seconds=tokens.expires_in)
    account.status = PaymentAccount.STATUS_CONNECTED
    account.save(update_fields=['access_token', 'refresh_token', 'token_expires_at',
                                'status', 'updated_at'])
    return account.access_token


def _clp(value) -> Decimal:
    return Decimal(int(round(float(value))))


def resolve_payment_account(*, organization, branch=None):
    """Cuenta a la que le entra el dinero de un cobro de esta sucursal.

    Orden de resolución: cuenta propia de la sede si está CONECTADA → cuenta PRINCIPAL de
    la organización (``branch IS NULL``). Si no hay ninguna conectada devuelve ``None`` y
    el caller levanta ``NotConnected``, igual que antes de las cuentas por sede. Una
    organización sin ninguna sede marcada resuelve SIEMPRE a la principal: el
    comportamiento de hoy, intacto.

    Una cuenta de sede DESCONECTADA cae a la principal a propósito: la sede "dejó de tener
    cuenta propia" hasta que reconecte, y así el gimnasio sigue vendiendo en vez de quedarse
    sin checkout.

    El chequeo de que ``branch`` es de ``organization`` es DEFENSA EN PROFUNDIDAD, no la
    guarda primaria: los callers validan la pertenencia ANTES de llegar acá (lección 8.3, la
    resolución de cuenta corre después de las guardas). Si igual llegara una sede de otra
    organización se levanta ``CheckoutError`` en vez de resolver: nunca cobrar contra la
    cuenta —ni contra la topología— de otro tenant.
    """
    if branch is not None and branch.organization_id != organization.id:
        raise CheckoutError('La sucursal no pertenece a la organización.')

    connected = PaymentAccount.objects.filter(
        organization=organization, provider=settings.PAYMENTS_PROVIDER,
        status=PaymentAccount.STATUS_CONNECTED)
    if branch is not None:
        account = connected.filter(branch=branch).first()
        if account is not None:
            return account
    return connected.filter(branch__isnull=True).first()


def _account_for_transaction(tx):
    """Cuenta con la que se emitió el cobro de ``tx`` (para validar/consultar el pago).

    Se lee de ``tx.payment_account`` —estampada en el checkout— y NO se re-resuelve por
    (organización, sede): entre el checkout y la notificación la sede pudo conectar o
    desconectar su cuenta, y validar el ``collector_id`` contra otra cuenta daría un
    ``PaymentIntegrityError`` falso sobre un pago legítimo (o un fetch con token ajeno).

    La re-lectura intersecta ``organization_id`` (y el proveedor) aunque la FK sea propia de
    la transacción: seguir una FK propia sin intersectar la organización es el agujero
    multi-tenant recurrente del repo.

    ``payment_account`` NULL = fila anterior a las cuentas por sede: ahí la única cuenta que
    pudo cobrar era la principal, así que ese es el fallback.
    """
    if tx.payment_account_id:
        return PaymentAccount.objects.filter(
            id=tx.payment_account_id, organization_id=tx.organization_id,
            provider=tx.provider).first()
    return PaymentAccount.objects.filter(
        organization_id=tx.organization_id, provider=tx.provider,
        branch__isnull=True).first()


def create_checkout(*, organization, user, plan=None, target_student_plan=None):
    if bool(plan) == bool(target_student_plan):
        raise CheckoutError('Debe indicarse exactamente uno: plan o target_student_plan.')

    plan_amount = Decimal('0')
    enrollment_fee_amount = Decimal('0')
    items = []
    # Sede de lo que se paga; se lee DESPUÉS de las guardas de pertenencia de cada rama
    # (lección 8.3). NULL = plan global o membresía sin sede → cobra la cuenta principal.
    branch = None

    if plan is not None:
        if plan.organization_id != organization.id:
            raise CheckoutError('El plan no pertenece a la organización.')
        if plan.plan_type in Plan.NOT_PURCHASABLE_ONLINE:
            raise CheckoutError('Este plan no se puede comprar en línea.')
        branch = plan.branch
        discount = plan.discount_percentage or 0
        plan_amount = _clp(max(float(plan.price) * (1 - discount / 100), 0))
        items.append(CheckoutItem(title=f'Plan {plan.name}', quantity=1, unit_price=plan_amount))
    else:
        sp = target_student_plan
        if sp.user_id != user.id or sp.plan.organization_id != organization.id:
            raise CheckoutError('La matrícula no corresponde al alumno/organización.')
        if not (sp.enrollment_fee and sp.enrollment_fee > 0) or sp.enrollment_fee_paid_at is not None:
            raise CheckoutError('No hay matrícula pendiente para este plan.')
        branch = sp.branch
        enrollment_fee_amount = _clp(sp.enrollment_fee)
        items.append(CheckoutItem(title='Matrícula', quantity=1, unit_price=enrollment_fee_amount))

    account = resolve_payment_account(organization=organization, branch=branch)
    if account is None:
        raise NotConnected('La organización no tiene MercadoPago conectado.')

    amount = plan_amount + enrollment_fee_amount

    tx = PaymentTransaction.objects.create(
        organization=organization, user=user, provider=account.provider,
        branch=branch, payment_account=account,
        plan=plan, plan_amount=plan_amount, enrollment_fee_amount=enrollment_fee_amount,
        amount=amount, currency='CLP', target_student_plan=target_student_plan,
        metadata={'items': [it.title for it in items]},
    )

    provider = get_payment_provider(account.provider)
    access_token = get_valid_access_token(account=account)
    apex = settings.PAYMENTS_APEX_BASE_URL.rstrip('/')
    result_url = f'{organization_public_base_url(organization)}/pagos/resultado?tx={tx.id}'
    session = provider.create_checkout(
        access_token=access_token,
        external_reference=str(tx.id),
        items=items,
        payer_email=getattr(user, 'email', None),
        back_urls=BackUrls(success=result_url, pending=result_url, failure=result_url),
        notification_url=f'{apex}/api/payments/webhook/?tx={tx.id}',
        expires_at=None,
    )
    tx.provider_preference_id = session.provider_preference_id
    tx.save(update_fields=['provider_preference_id', 'updated_at'])
    return tx, session.redirect_url


def apply_provider_payment(*, tx, payment):
    """Núcleo idempotente. Debe llamarse por webhook y por reconcile."""
    # El mismatch de organización NO puede escapar del atomic: haría rollback del `tx.save()`
    # y la transacción quedaría igual que un checkout abandonado (`pending`, sin
    # `provider_payment_id`) sobre un pago YA COBRADO. Peor: `reconcile_payments` exige
    # `provider_payment_id__isnull=False`, o sea justo el campo que el rollback borra, así
    # que el pago quedaba irrecuperable. Se registra la señal, se comitea, y se levanta
    # DESPUÉS del bloque.
    plan_org_mismatch = None
    with db_transaction.atomic():
        tx = PaymentTransaction.objects.select_for_update().get(pk=tx.pk)
        if tx.processed_at is not None:
            return tx   # ya activado: no-op

        # La cuenta que emitió ESTE cobro (ver `_account_for_transaction`): con varias
        # cuentas por organización —principal + sedes— un `.first()` por (organización,
        # proveedor) elige una al azar y la validación de collector deja de significar nada.
        account = _account_for_transaction(tx)
        if (not payment.collector_id or not account or not account.provider_user_id
                or str(payment.collector_id) != str(account.provider_user_id)):
            raise PaymentIntegrityError('collector_id no coincide con la cuenta del gym.')
        if payment.external_reference and str(payment.external_reference) != str(tx.id):
            raise PaymentIntegrityError('external_reference no coincide.')

        tx.provider_payment_id = payment.provider_payment_id
        tx.status = payment.status.value
        tx.status_detail = payment.status_detail
        tx.raw_provider_payload = payment.raw

        if payment.status == PaymentStatus.APPROVED:
            if payment.amount != tx.amount:
                raise PaymentIntegrityError(f'monto {payment.amount} != esperado {tx.amount}')
            from .plans import PlanOrganizationMismatch, activate_student_plan
            if tx.plan_id:
                try:
                    sp = activate_student_plan(student=tx.user, plan=tx.plan,
                                               start_date=timezone.localdate())
                except PlanOrganizationMismatch as exc:
                    # El alumno cambió de organización entre el checkout y la aprobación:
                    # activar el plan crearía una membresía que ningún endpoint muestra ni
                    # consume. Se deja la tx COBRADA y SIN `processed_at` para que quede
                    # visible y recuperable, y se aborta después del atomic.
                    plan_org_mismatch = str(exc)
                    tx.status_detail = f'{payment.status_detail or ""} | plan_org_mismatch'.strip(' |')
                else:
                    tx.student_plan = sp
            elif tx.target_student_plan_id:
                sp = tx.target_student_plan
                sp.enrollment_fee_paid_at = timezone.now()
                sp.save(update_fields=['enrollment_fee_paid_at', 'updated_at'])
                tx.student_plan = sp
            if plan_org_mismatch is None:
                tx.processed_at = timezone.now()

        tx.save()

    if plan_org_mismatch is not None:
        # PaymentIntegrityError y no otra: es una inconsistencia, no un fallo transitorio.
        # La vista del webhook la ackea con 200 y no re-encola.
        raise PaymentIntegrityError(plan_org_mismatch)
    return tx


def process_payment_notification(*, tx_id, provider_payment_id):
    tx = PaymentTransaction.objects.filter(id=tx_id).select_related(
        'organization', 'user', 'plan', 'target_student_plan').first()
    if tx is None:
        return None
    # La cuenta del checkout, no una re-resuelta: el pago lo cobró ESA cuenta y solo su
    # token puede consultarlo en MP (ver `_account_for_transaction`).
    account = _account_for_transaction(tx)
    # Cuenta ausente o desconectada (tokens vaciados): no se puede/ debe consultar a MP.
    # Abortamos limpio (ack del webhook) en vez de intentar refrescar un token nulo, que
    # con MP real da 400 → PaymentProviderError → 500 y bucle de reintentos del webhook.
    # Si la sede desconectó su cuenta después del checkout NO se cae a la principal: el
    # pago vive en la cuenta de la sede y con el token de otra cuenta el fetch da 404/403.
    if account is None or account.status != PaymentAccount.STATUS_CONNECTED:
        return None
    provider = get_payment_provider(tx.provider)
    access_token = get_valid_access_token(account=account)
    payment = provider.fetch_payment(access_token=access_token,
                                     provider_payment_id=provider_payment_id)
    return apply_provider_payment(tx=tx, payment=payment)


def reconcile_transaction(*, tx):
    if tx.provider_payment_id:
        return process_payment_notification(tx_id=tx.id,
                                            provider_payment_id=tx.provider_payment_id)
    return tx
