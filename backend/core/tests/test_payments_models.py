import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction as db_tx

from core.models import PaymentAccount, PaymentTransaction


@pytest.fixture
def enc_key(settings):
    from core.fields import generate_encryption_key
    settings.PAYMENTS_ENCRYPTION_KEY = generate_encryption_key()


def test_payment_account_tokens_encrypted_at_rest(db, enc_key, make_organization):
    org = make_organization()
    acc = PaymentAccount.objects.create(
        organization=org, provider='mercadopago', provider_user_id='u1',
        access_token='AT', refresh_token='RT', status=PaymentAccount.STATUS_CONNECTED,
    )
    acc.refresh_from_db()
    assert acc.access_token == 'AT'          # se descifra al leer
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute('SELECT access_token FROM core_paymentaccount WHERE id=%s', [acc.id])
        raw = cur.fetchone()[0]
    assert raw != 'AT'                        # cifrado en DB


def test_payment_account_unique_per_org_provider(db, enc_key, make_organization):
    org = make_organization()
    PaymentAccount.objects.create(organization=org, provider='mercadopago',
                                  provider_user_id='u1', access_token='a', refresh_token='b')
    with pytest.raises(IntegrityError):
        PaymentAccount.objects.create(organization=org, provider='mercadopago',
                                      provider_user_id='u2', access_token='c', refresh_token='d')


def test_transaction_uuid_pk_and_defaults(db, make_organization, make_user):
    org = make_organization()
    student = make_user('stu', organization=org, role='student')
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, provider='mercadopago',
        amount=Decimal('10000'), plan_amount=Decimal('10000'), enrollment_fee_amount=Decimal('0'),
    )
    assert isinstance(tx.id, uuid.UUID)
    assert tx.status == 'pending'
    assert tx.currency == 'CLP'
    assert tx.processed_at is None


def test_unique_provider_payment_id(db, make_organization, make_user):
    org = make_organization()
    student = make_user('stu2', organization=org, role='student')
    common = dict(organization=org, user=student, provider='mercadopago',
                  amount=Decimal('1'), plan_amount=Decimal('1'), enrollment_fee_amount=Decimal('0'))
    PaymentTransaction.objects.create(provider_payment_id='PAY1', **common)
    with pytest.raises(IntegrityError):
        with db_tx.atomic():
            PaymentTransaction.objects.create(provider_payment_id='PAY1', **common)
    # Múltiples NULL sí se permiten (constraint condicional):
    with db_tx.atomic():
        PaymentTransaction.objects.create(provider_payment_id=None, **common)
        PaymentTransaction.objects.create(provider_payment_id=None, **common)
