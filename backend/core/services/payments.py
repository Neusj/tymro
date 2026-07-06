"""Orquestación de dominio de pagos. No sabe de HTTP ni de MercadoPago:
delega en get_payment_provider(). Aísla la lógica de negocio de las views.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.utils import timezone

from core.models import PaymentAccount, PaymentTransaction
from .providers import PaymentProviderError, get_payment_provider
from .providers.base import BackUrls, CheckoutItem

STATE_SALT = 'payments-oauth'
STATE_MAX_AGE = 600          # 10 minutos
REFRESH_MARGIN = timedelta(hours=24)


class InvalidState(Exception):
    """El parámetro state del callback OAuth no es válido/expiró."""


class CheckoutError(Exception):
    """No se puede iniciar el cobro."""


class NotConnected(CheckoutError):
    """La organización no tiene cuenta de pago conectada."""


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
    frontend = getattr(settings, 'FRONTEND_URL', apex).rstrip('/')
    session = provider.create_checkout(
        access_token=access_token,
        external_reference=str(tx.id),
        items=items,
        payer_email=getattr(user, 'email', None),
        back_urls=BackUrls(success=f'{frontend}/pagos/resultado?tx={tx.id}',
                           pending=f'{frontend}/pagos/resultado?tx={tx.id}',
                           failure=f'{frontend}/pagos/resultado?tx={tx.id}'),
        notification_url=f'{apex}/api/payments/webhook/?tx={tx.id}',
        expires_at=None,
    )
    tx.provider_preference_id = session.provider_preference_id
    tx.save(update_fields=['provider_preference_id', 'updated_at'])
    return tx, session.redirect_url
