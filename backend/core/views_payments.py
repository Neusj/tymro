"""APIViews de pagos (MercadoPago). Split de views.py por tamaño.
Todas respetan multitenancy: connect/account filtran por request.user.organization;
el callback resuelve la org por el state firmado (nunca por el Host)."""
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentAccount, PaymentTransaction, Plan, StudentPlan, WebhookEvent
from .serializers import (PaymentAccountSerializer, PaymentCheckoutRequestSerializer,
                          PaymentTransactionStatusSerializer)
from .services import payments
from .services.providers import get_payment_provider
from .views import _is_gym_admin, _is_student, _is_superadmin   # helpers de rol existentes


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
        url = payments.build_connect_url(organization=user.organization)
        return Response({'authorization_url': url})


class PaymentOAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state')
        frontend = getattr(settings, 'FRONTEND_URL', '') or settings.PAYMENTS_APEX_BASE_URL
        if not code or not state:
            return redirect(f'{frontend}/ajustes/pagos?connected=0')
        try:
            payments.connect_callback(code=code, state=state)
        except payments.InvalidState:
            return redirect(f'{frontend}/ajustes/pagos?connected=0&error=state')
        except Exception:
            return redirect(f'{frontend}/ajustes/pagos?connected=0&error=exchange')
        return redirect(f'{frontend}/ajustes/pagos?connected=1')


class PaymentAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            return Response({'detail': 'No tienes permisos.'}, status=status.HTTP_403_FORBIDDEN)
        account = PaymentAccount.objects.filter(
            organization_id=user.organization_id, provider=settings.PAYMENTS_PROVIDER).first()
        if account is None:
            return Response({'status': 'disconnected', 'provider': settings.PAYMENTS_PROVIDER})
        return Response(PaymentAccountSerializer(account).data)


class PaymentCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not _is_student(user):
            return Response({'detail': 'Solo alumnos pueden pagar.'}, status=status.HTTP_403_FORBIDDEN)
        req = PaymentCheckoutRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        plan = target = None
        if req.validated_data.get('plan_id'):
            plan = get_object_or_404(Plan, id=req.validated_data['plan_id'],
                                     organization_id=user.organization_id)
        else:
            target = get_object_or_404(StudentPlan, id=req.validated_data['target_student_plan_id'],
                                       user=user)
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
            except payments.PaymentIntegrityError:
                # No re-encolar: es una inconsistencia, no un fallo transitorio.
                return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_200_OK)
