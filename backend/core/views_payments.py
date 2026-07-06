"""APIViews de pagos (MercadoPago). Split de views.py por tamaño.
Todas respetan multitenancy: connect/account filtran por request.user.organization;
el callback resuelve la org por el state firmado (nunca por el Host)."""
from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentAccount
from .serializers import PaymentAccountSerializer
from .services import payments
from .views import _is_gym_admin, _is_superadmin   # helpers de rol existentes


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
