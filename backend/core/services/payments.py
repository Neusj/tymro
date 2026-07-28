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


def _sign_state(organization_id) -> str:
    # nonce derivado del org_id + timestamp implícito de signing (no usamos Math.random).
    return signing.dumps({'org': organization_id}, salt=STATE_SALT)


def _load_state(state) -> int:
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidState('state inválido o expirado') from exc
    return data['org']


def build_connect_url(*, organization) -> str:
    provider = get_payment_provider()
    state = _sign_state(organization.id)
    return provider.get_authorization_url(state=state, redirect_uri=settings.MP_OAUTH_REDIRECT_URI)


def organization_from_state(state):
    """Valida el ``state`` firmado y devuelve la Organization que viaja en él.
    Levanta InvalidState si el state es inválido/expiró o la org ya no existe.
    Se usa en el callback OAuth para saber a qué subdominio volver (el callback
    llega al apex; el tenant no viaja en el host, solo en el state)."""
    from core.models import Organization
    org_id = _load_state(state)
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
    from core.models import Organization
    org_id = _load_state(state)
    organization = Organization.objects.get(id=org_id)
    provider = get_payment_provider()
    tokens = provider.exchange_code(code=code, redirect_uri=settings.MP_OAUTH_REDIRECT_URI)
    now = timezone.now()
    account, _ = PaymentAccount.objects.update_or_create(
        organization=organization, provider=provider.name,
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


def create_checkout(*, organization, user, plan=None, target_student_plan=None):
    if bool(plan) == bool(target_student_plan):
        raise CheckoutError('Debe indicarse exactamente uno: plan o target_student_plan.')

    account = PaymentAccount.objects.filter(
        organization=organization, provider=settings.PAYMENTS_PROVIDER,
        status=PaymentAccount.STATUS_CONNECTED).first()
    if account is None:
        raise NotConnected('La organización no tiene MercadoPago conectado.')

    plan_amount = Decimal('0')
    enrollment_fee_amount = Decimal('0')
    items = []

    if plan is not None:
        if plan.organization_id != organization.id:
            raise CheckoutError('El plan no pertenece a la organización.')
        if plan.plan_type in Plan.NOT_PURCHASABLE_ONLINE:
            raise CheckoutError('Este plan no se puede comprar en línea.')
        discount = plan.discount_percentage or 0
        plan_amount = _clp(max(float(plan.price) * (1 - discount / 100), 0))
        items.append(CheckoutItem(title=f'Plan {plan.name}', quantity=1, unit_price=plan_amount))
    else:
        sp = target_student_plan
        if sp.user_id != user.id or sp.plan.organization_id != organization.id:
            raise CheckoutError('La matrícula no corresponde al alumno/organización.')
        if not (sp.enrollment_fee and sp.enrollment_fee > 0) or sp.enrollment_fee_paid_at is not None:
            raise CheckoutError('No hay matrícula pendiente para este plan.')
        enrollment_fee_amount = _clp(sp.enrollment_fee)
        items.append(CheckoutItem(title='Matrícula', quantity=1, unit_price=enrollment_fee_amount))

    amount = plan_amount + enrollment_fee_amount

    tx = PaymentTransaction.objects.create(
        organization=organization, user=user, provider=account.provider,
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

        account = PaymentAccount.objects.filter(
            organization_id=tx.organization_id, provider=tx.provider).first()
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
    account = PaymentAccount.objects.filter(
        organization_id=tx.organization_id, provider=tx.provider).first()
    # Cuenta ausente o desconectada (tokens vaciados): no se puede/ debe consultar a MP.
    # Abortamos limpio (ack del webhook) en vez de intentar refrescar un token nulo, que
    # con MP real da 400 → PaymentProviderError → 500 y bucle de reintentos del webhook.
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
