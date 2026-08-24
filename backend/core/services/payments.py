"""Orquestación de dominio de pagos. No sabe de HTTP ni de MercadoPago:
delega en get_payment_provider(). Aísla la lógica de negocio de las views.
"""
import logging
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core import signing
from django.db import transaction as db_transaction
from django.utils import timezone

from core.models import PaymentAccount, PaymentTransaction, Plan
from .plans import quote_plan_purchase
from .providers import PaymentProviderError, get_payment_provider
from .providers.base import BackUrls, CheckoutItem, PaymentStatus, RevocationUnverified
from .public_urls import organization_public_base_url

logger = logging.getLogger(__name__)

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


def _revocation_access_token(provider, *, access_token, refresh_token, token_expires_at):
    """Token con el que INTENTAR la revocación, resuelto SOLO EN MEMORIA.

    Recibe el snapshot que ``disconnect_account`` leyó de la fila ANTES de vaciarla, no la
    fila: para cuando esto corre, la fila ya está desconectada y con los tokens en NULL, y
    así tiene que quedar.

    Por qué no se reusa ``get_valid_access_token(account=account)``, que hace justo este
    cálculo: porque ESCRIBE en la fila (guarda los tokens nuevos y pone `status=CONNECTED`).
    Llamarla DESPUÉS del vaciado RESUCITARÍA la cuenta a `connected` con tokens frescos —el
    gimnasio quedaría reconectado por el acto de desconectarse—, y llamarla ANTES
    reintroduciría exactamente la llamada de red previa al vaciado que el orden nuevo
    elimina. Así que se duplica el criterio de expiración (el mismo `REFRESH_MARGIN`) a
    cambio de que el resultado sea EFÍMERO: vive en esta variable y muere con el request.

    Por qué refrescar y no mandar el `access_token` crudo: los access_token de MP duran
    hasta 180 días y solo se renuevan cuando alguien cobra, así que un gimnasio que conectó
    y nunca vendió tiene en la fila un token VENCIDO. Revocar con él da 401 → revocación no
    confirmada → autorización viva en MP. El `refresh_token` es lo único que puede producir
    una credencial usable en ese escenario.

    Si el refresh falla se devuelve igual el `access_token` crudo: puede seguir vivo (el
    fallo pudo ser un 5xx o un timeout), y un intento con un token quizás bueno es mejor
    que no intentar. Si tampoco hay, devuelve None y el caller no llama a la red.
    """
    expiring = (token_expires_at is None
                or token_expires_at <= timezone.now() + REFRESH_MARGIN)
    if expiring and refresh_token:
        try:
            tokens = provider.refresh_tokens(refresh_token=refresh_token)
        except Exception:
            # Sin log del detalle acá: si después la revocación tampoco confirma, el caller
            # ya emite el warning con los identificadores de la fila. Duplicarlo sería ruido.
            pass
        else:
            # NUNCA se guarda en la fila. Ver el docstring: ese guardado es exactamente lo
            # que convertiría una desconexión en una reconexión.
            return tokens.access_token
    return access_token


def disconnect_account(account) -> PaymentAccount:
    """Desconecta la cuenta: borra los tokens locales y DESPUÉS revoca en el proveedor.

    INVARIANTE, y es el punto de toda la función: al volver de acá la fila SIEMPRE queda
    ``disconnected`` con ``access_token``/``refresh_token``/``token_expires_at`` en NULL,
    pase lo que pase con la red — incluso si el worker MUERE durante la revocación.

    Orden exacto, y el orden importa:

    1. Copia a variables LOCALES lo que hace falta para revocar (tokens, expiración,
       ``provider_user_id``, nombre del proveedor) ANTES de mutar nada.
    2. VACÍA LA FILA YA: `disconnected` + los tres campos de token a NULL, y `save`. Esto
       no depende de la red, no está dentro de ningún try, y no puede quedar a medias.
    3. RECIÉN AHÍ intenta ``provider.revoke(...)``, BEST-EFFORT, con las variables locales.
       Cualquier fallo se loguea como warning y la función SIGUE. Sin tokens (cuenta ya
       desconectada) ni siquiera se toca la red: no hay nada que revocar.

    POR QUÉ ESTE ORDEN Y NO EL INVERSO (que fue la primera versión de P3.3): revocar primero
    parece razonable —"después del vaciado no habría con qué autenticar"— pero ese argumento
    es FALSO: el token ya está en una variable local, la fila no hace falta. Y el orden
    inverso tiene una falla real: `_TIMEOUT` de `requests` son 15 s que aplican POR SEPARADO
    a connect y a read (~30 s en el peor caso), mientras gunicorn corre con workers sync y
    `--timeout` 30 s (ver `entrypoint.sh`). Si el proveedor acepta la conexión y no responde,
    el arbiter mata al worker con una SEÑAL, no con una excepción: el `except Exception` de
    abajo NO la cubre y el vaciado local NUNCA corre. Resultado: la fila queda `connected`
    con el token guardado y el panel diciendo "Conectada", cuando encima la request pudo
    llegar al proveedor y matar el token allá. El peor de los dos mundos. Con este orden esa
    ventana no existe: lo único que se pierde si el worker muere es el intento de revocación,
    que ya era best-effort.

    Hasta P3.3 solo existía el vaciado local, así que el token real seguía vivo del lado de
    MercadoPago hasta caducar (hasta 180 días) bajo nuestro ``app_id``, aunque el gimnasio
    viera "desconectado". Ahora se intenta matarlo de verdad; los límites de ese intento
    están documentados en ``MercadoPagoProvider.revoke``.

    NO borra la fila: se conserva el histórico y la reconexión posterior vía el
    ``update_or_create`` de ``connect_callback`` vuelve a rellenar los tokens.
    El scoping por organización es responsabilidad de la view que obtiene ``account``."""
    # 1. SNAPSHOT antes de tocar nada. `provider` también: `account.provider` se lee ahora
    # por simetría y para que el bloque de revocación no dependa de la instancia mutada.
    access_token = account.access_token
    refresh_token = account.refresh_token
    token_expires_at = account.token_expires_at
    provider_user_id = account.provider_user_id
    provider_name = account.provider

    # 2. VACIADO LOCAL INCONDICIONAL. Fuera de cualquier try y antes de cualquier I/O de red:
    # es lo único que el producto puede garantizar, así que no puede depender de nadie.
    account.status = PaymentAccount.STATUS_DISCONNECTED
    account.access_token = None
    account.refresh_token = None
    account.token_expires_at = None
    account.save(update_fields=['status', 'access_token', 'refresh_token',
                                'token_expires_at', 'updated_at'])

    # 3. Revocación BEST-EFFORT, ya con la fila limpia.
    if not access_token and not refresh_token:
        # Cuenta ya desconectada (o fila sin tokens): no hay nada que revocar y la llamada
        # solo produciría un 401 esperable, que además ahora se reporta como no-confirmado.
        return account
    if not provider_user_id:
        # Sin `provider_user_id` NO se puede revocar, y callar sería peor que no intentarlo:
        # la URL de revocación lo interpola (`/users/{user_id}/applications/{app_id}`), así
        # que vacío produce `/users//applications/...` → 404 → y la regla "404 = ya estaba
        # revocado" de `MercadoPagoProvider.revoke` lo contaría como ÉXITO. O sea: un no-op
        # silencioso que deja el token vivo mientras el log dice que todo salió bien.
        # `provider_user_id` puede quedar vacío legítimamente: `exchange_code` lo llena con
        # `str(data.get('user_id', ''))`, así que una respuesta de MP sin `user_id` deja la
        # cuenta conectada y sin ancla para revocar. Se loguea y se sale: el vaciado ya pasó.
        logger.warning(
            'Cuenta de pago sin provider_user_id: no se puede revocar el token en el '
            'proveedor, solo se borra localmente (account=%s organization=%s branch=%s '
            'provider=%s)',
            account.pk, account.organization_id, account.branch_id, account.provider)
        return account
    try:
        # El proveedor que EMITIÓ este token, no el default global — mismo criterio que
        # `get_valid_access_token`: si `settings.PAYMENTS_PROVIDER` cambió después de la
        # conexión, revocar contra el proveedor nuevo apuntaría a otra app (o reventaría),
        # y el token viejo quedaría vivo justo en el caso en que más importa.
        provider = get_payment_provider(provider_name)
        revocation_token = _revocation_access_token(
            provider, access_token=access_token, refresh_token=refresh_token,
            token_expires_at=token_expires_at)
        if revocation_token:
            provider.revoke(access_token=revocation_token,
                            provider_user_id=provider_user_id)
        else:
            # SIN `else` esto era un no-op SILENCIOSO, justo la clase de agujero que este
            # camino existe para cerrar: se llega acá con `access_token` vacío pero
            # `refresh_token` presente (pasa la guarda de más arriba) y el refresh falla, así
            # que no queda ningún token con el que autenticar el DELETE. La desconexión local
            # ya está hecha y es correcta, pero la autorización puede seguir viva del lado del
            # proveedor y nadie se enteraría. Se loguea con los mismos identificadores que los
            # otros dos caminos de skip para que la reconciliación manual sea posible.
            logger.warning(
                'No quedó ningún token con el que revocar al desconectar cuenta de pago: la '
                'autorización puede seguir viva del lado del proveedor; reconciliar a mano en '
                'el panel de MercadoPago (account=%s organization=%s branch=%s provider=%s)',
                account.pk, account.organization_id, account.branch_id, account.provider)
    except RevocationUnverified as exc:
        # ANTES del `except Exception`, o el genérico se lo come (es subclase de
        # PaymentProviderError). Es un caso DISTINTO de "falló": el proveedor contestó, pero
        # no pudimos autenticar, así que NO sabemos si la autorización murió. Como la fila ya
        # está vacía, no queda ningún token con el que reintentar: la única salida es que un
        # humano entre al panel de MercadoPago del gimnasio y quite la app a mano. Por eso el
        # mensaje lo dice explícitamente, con qué fila mirar.
        logger.warning(
            'Revocación en el proveedor NO CONFIRMADA al desconectar cuenta de pago: la '
            'autorización puede seguir viva del lado del proveedor; reconciliar a mano en '
            'el panel de MercadoPago (account=%s organization=%s branch=%s provider=%s): %s',
            account.pk, account.organization_id, account.branch_id, account.provider, exc)
    except Exception as exc:      # amplio A PROPÓSITO — ver abajo
        # `except Exception` A PROPÓSITO, y no solo `PaymentProviderError`: un bug del
        # proveedor (TypeError, un mock mal armado, un error inesperado de la librería HTTP)
        # no puede convertir una desconexión en un 500 para el gimnasio. Con el orden nuevo
        # el vaciado local YA ocurrió antes de este try, así que ninguna excepción de acá
        # puede dejar la fila a medias; este catch solo protege la respuesta del endpoint.
        #
        # Nunca se loguea el token (es un secreto en reposo cifrado): solo identificadores
        # de la fila, que es lo que hace falta para reconciliar a mano en MP si importa.
        logger.warning(
            'Revocación en el proveedor falló al desconectar cuenta de pago '
            '(account=%s organization=%s branch=%s provider=%s): %s',
            account.pk, account.organization_id, account.branch_id, account.provider, exc)
    return account


def get_valid_access_token(*, account) -> str:
    """Access token usable de ``account``, refrescándolo si está por vencer.

    OJO, ESCRIBE EN LA FILA: al refrescar guarda los tokens nuevos y pone
    ``status=CONNECTED`` (y al fallar, ``DISCONNECTED``). Por eso ``disconnect_account``
    NO la usa —resucitaría la cuenta que acaba de vaciar— y resuelve su token en memoria
    con ``_revocation_access_token``. Cualquier caller nuevo tiene que asumir la escritura.
    """
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
    plan_original_amount = Decimal('0')
    discount_percentage = 0
    discount_amount = Decimal('0')
    discount_source = ''
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
        quote = quote_plan_purchase(student=user, plan=plan)
        plan_original_amount = quote.original_amount
        discount_percentage = float(quote.discount_percentage)
        discount_amount = quote.discount_amount
        discount_source = quote.discount_source
        plan_amount = _clp(quote.final_amount)
        items.append(CheckoutItem(title=f'Plan {plan.name}', quantity=1, unit_price=plan_amount))
    else:
        sp = target_student_plan
        if sp.user_id != user.id or sp.plan.organization_id != organization.id:
            raise CheckoutError('La matrícula no corresponde al alumno/organización.')
        from .plans import enrollment_fee_is_valid
        if not getattr(sp.user, 'pays_enrollment_fee', True):
            raise CheckoutError('Este alumno no tiene matrícula pendiente para cobrar.')
        if not (sp.enrollment_fee and sp.enrollment_fee > 0) or enrollment_fee_is_valid(
            sp, timezone.localdate(),
        ):
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
        plan=plan,
        plan_original_amount=plan_original_amount,
        plan_amount=plan_amount,
        discount_percentage=discount_percentage,
        discount_amount=discount_amount,
        discount_source=discount_source,
        enrollment_fee_amount=enrollment_fee_amount,
        amount=amount, currency='CLP', target_student_plan=target_student_plan,
        metadata={'items': [it.title for it in items], 'discount_source': discount_source},
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


def _assert_payment_belongs_to_transaction(tx, payment):
    """Chequeos de integridad del pago contra la fila. Levanta ``PaymentIntegrityError``.

    Extraído de ``apply_provider_payment`` porque ahora hay DOS caminos que escriben la fila
    —aplicar el cobro y registrar la devolución— y los dos tienen que exigir lo mismo. Si el
    camino de devolución no validara el collector, cualquier pago de otro vendedor cuyo id
    llegue por el webhook podría marcar como devuelta una venta ajena.
    """
    # La cuenta que emitió ESTE cobro (ver `_account_for_transaction`): con varias
    # cuentas por organización —principal + sedes— un `.first()` por (organización,
    # proveedor) elige una al azar y la validación de collector deja de significar nada.
    account = _account_for_transaction(tx)
    if (not payment.collector_id or not account or not account.provider_user_id
            or str(payment.collector_id) != str(account.provider_user_id)):
        raise PaymentIntegrityError('collector_id no coincide con la cuenta del gym.')
    if payment.external_reference and str(payment.external_reference) != str(tx.id):
        raise PaymentIntegrityError('external_reference no coincide.')


def _stamp_refund(tx, payment):
    """Escribe la DEVOLUCIÓN en la fila (no guarda: el caller hace el `save`).

    Un solo lugar para los dos caminos que pueden recibirla: la devolución de un cobro ya
    aplicado (el caso normal) y la de uno que nunca se llegó a aplicar.

    El monto es `tx.amount` —lo que ESPERÁBAMOS cobrar y ya validamos contra el proveedor
    cuando el pago se aprobó— y no `payment.amount`: para un pago devuelto el proveedor
    informa el monto ORIGINAL de la transacción, no lo reembolsado, así que tomarlo de ahí
    no agregaría información y sí abriría la puerta a que un payload raro cambie el monto de
    una venta vieja. Por la misma razón acá NO se re-valida el monto: no hay nada que
    comparar, y abortar la devolución por un monto que el proveedor no promete informar
    dejaría el ingreso inflado, que es el estado que este código existe para arreglar.

    Se registra aunque `collected_at` sea NULL (devolución de algo que nunca contamos como
    cobrado): el hecho es el hecho. Es el REPORTE el que decide no restar lo que nunca sumó
    —ver `services/reports_revenue.py`—, y esa decisión vive allá para que la fila no tenga
    que mentir para que el neto cuadre.
    """
    tx.provider_payment_id = payment.provider_payment_id or tx.provider_payment_id
    # `refunded` cubre también el CONTRACARGO: `MercadoPagoProvider` mapea `refunded` y
    # `charged_back` al mismo `PaymentStatus.REFUNDED`. La distinción sobrevive en
    # `status_detail` y en `raw_provider_payload`, que se guardan enteros.
    tx.status = payment.status.value
    tx.status_detail = payment.status_detail
    tx.raw_provider_payload = payment.raw
    tx.refunded_at = timezone.now()
    tx.refunded_amount = tx.amount
    # TODO P3.4: la membresía activada por este cobro NO se desactiva. Es una decisión de
    # producto (un alumno que ya consumió clases con un plan que después se devolvió) y
    # excede el alcance de registrar el dinero. Lo que sí queda cerrado es que la plata
    # devuelta se resta del ingreso: antes de esto la devolución no existía en la base.


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
            # YA ACTIVADO. Hasta P3.4 esto era un no-op ABSOLUTO, y ahí estaba el agujero:
            # un `refunded`/`charged_back` que llegara después de la activación se descartaba
            # entero, así que el gimnasio devolvía la plata y el ingreso seguía contándola.
            # Ahora un único aviso posterior sigue teniendo efecto —la DEVOLUCIÓN— y todo lo
            # demás (el reintento del mismo cobro aprobado, que es el caso masivo del
            # webhook de MP) sale por el mismo return de antes, sin tocar la fila.
            if payment.status != PaymentStatus.REFUNDED:
                return tx
            _assert_payment_belongs_to_transaction(tx, payment)
            # ATADURA DURA, y solo en ESTE camino. `_assert_payment_belongs_to_transaction`
            # compara el `external_reference` únicamente SI viene (`if
            # payment.external_reference and ...`), porque un pago cobrado por la misma cuenta
            # de MercadoPago FUERA de nuestro checkout —QR en recepción, link del panel, Point—
            # llega sin él. Esa laxitud es vieja y en el camino de activación no se toca: es la
            # que permite que un cobro legítimo active el plan.
            #
            # Acá NO alcanza, y la diferencia es que este camino MUTA una fila de dinero YA
            # LIQUIDADA. El `?tx=` del webhook queda fuera del manifest del HMAC de MP
            # (`id;request-id;ts`, ver `MercadoPagoProvider.verify_webhook`), así que una
            # notificación con firma válida se puede RE-APUNTAR a otra transacción. Si el pago
            # referido no trae `external_reference`, lo único que quedaba en pie era el
            # collector — y `PaymentAccount` no tiene unicidad global de `provider_user_id`
            # (solo por organización y por sede), así que dos gimnasios del SaaS que conecten
            # el MISMO vendedor de MP (franquicia, dueño con dos locales) comparten collector y
            # lo pasan igual. Resultado posible: una venta ajena marcada `refunded` y el
            # reporte restando plata que nadie devolvió.
            #
            # Exigirlo no puede romper nada real: toda `tx` nace en `create_checkout`, que
            # manda `external_reference=str(tx.id)` a la preference, así que el pago de una
            # venta NUESTRA siempre lo trae. Un aviso de devolución sin él no es de esta venta.
            if str(payment.external_reference or '') != str(tx.id):
                raise PaymentIntegrityError(
                    'external_reference ausente o distinto: no se registra la devolución.')
            if tx.refunded_at is not None:
                return tx   # devolución ya registrada: idempotente, igual que el cobro
            _stamp_refund(tx, payment)
            tx.save()
            return tx

        _assert_payment_belongs_to_transaction(tx, payment)

        tx.provider_payment_id = payment.provider_payment_id
        tx.status = payment.status.value
        tx.status_detail = payment.status_detail
        tx.raw_provider_payload = payment.raw

        if payment.status == PaymentStatus.REFUNDED:
            # Devolución de un cobro que NUNCA se aplicó: o la notificación de aprobación
            # nunca llegó, o llegó y la activación abortó (`plan_org_mismatch`). Se registra
            # igual —el aviso es un hecho— y `_stamp_refund` sobreescribe los tres campos de
            # estado que se acaban de asignar arriba con los mismos valores.
            _stamp_refund(tx, payment)

        if payment.status == PaymentStatus.APPROVED:
            if payment.amount != tx.amount:
                raise PaymentIntegrityError(f'monto {payment.amount} != esperado {tx.amount}')
            # LA PLATA ENTRÓ. Se estampa ACÁ —después de validar el monto y ANTES de intentar
            # activar la membresía— porque el ingreso bruto del reporte se cuenta por este
            # campo: si dependiera de que la activación funcione, el `plan_org_mismatch` de
            # más abajo (que deja la fila cobrada y sin `processed_at` a propósito) escondería
            # del reporte una venta que el gimnasio efectivamente cobró.
            # `or timezone.now()` en vez de asignación directa: `collected_at` es histórico y
            # se escribe UNA vez; un reintento del webhook no puede moverlo de período.
            tx.collected_at = tx.collected_at or timezone.now()
            from .plans import PlanOrganizationMismatch, activate_student_plan
            if tx.plan_id:
                tx_discount = (
                    tx.discount_percentage
                    if tx.discount_source or (tx.discount_percentage or 0) > 0
                    else None
                )
                try:
                    sp = activate_student_plan(student=tx.user, plan=tx.plan,
                                               start_date=timezone.localdate(),
                                               discount_percentage=tx_discount,
                                               discount_source=tx.discount_source)
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
                paid_at = timezone.now()
                sp.enrollment_fee_paid_at = paid_at
                sp.enrollment_fee_due_at = timezone.localtime(paid_at).date() + timedelta(days=365)
                sp.save(update_fields=['enrollment_fee_paid_at', 'enrollment_fee_due_at', 'updated_at'])
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
