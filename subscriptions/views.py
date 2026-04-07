from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
import jwt
from datetime import datetime, timedelta

from .models import Tenant, Plan, Suscripcion, Usuario, LogAuditoria
from .serializers import (
    TenantSerializer, PlanSerializer, SuscripcionSerializer,
    UsuarioSerializer, UsuarioCreateSerializer, LoginSerializer,
    CambioPasswordSerializer, LogAuditoriaSerializer
)


def get_client_ip(request):
    """Obtiene la IP del cliente."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


class CsrfTokenView(APIView):
    """Obtiene el token CSRF para requests desde el frontend."""
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class RegisterView(APIView):
    """Registro de nuevos usuarios con tenant automatico."""
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        # Validar datos del usuario
        user_serializer = UsuarioCreateSerializer(data=request.data)
        if not user_serializer.is_valid():
            return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Obtener plan gratuito por defecto
        plan_free = Plan.objects.filter(slug="free", activo=True).first()
        
        # Crear tenant
        tenant_data = request.data.get("tenant", {})
        tenant = Tenant.objects.create(
            nombre=tenant_data.get("nombre", user_serializer.validated_data["username"]),
            slug=tenant_data.get("slug", user_serializer.validated_data["username"].lower().replace(" ", "-")),
            email=user_serializer.validated_data["email"],
            telefono=tenant_data.get("telefono", ""),
            estado=Tenant.Estado.TRIAL if plan_free and plan_free.dias_trial > 0 else Tenant.Estado.ACTIVO,
            fecha_expiracion_trial=timezone.now() + timedelta(days=plan_free.dias_trial if plan_free else 7) if plan_free and plan_free.dias_trial > 0 else None,
        )
        
        # Crear usuario
        user = user_serializer.save()
        user.tenant = tenant
        user.save()
        
        # Crear suscripcion
        if plan_free:
            Suscripcion.objects.create(
                tenant=tenant,
                plan=plan_free,
                estado=Suscripcion.Estado.TRIAL if plan_free.dias_trial > 0 else Suscripcion.Estado.ACTIVA,
                periodicidad=Plan.Periodicidad.MENSUAL,
                fecha_inicio=timezone.now(),
                fecha_expiracion=timezone.now() + timedelta(days=plan_free.dias_trial if plan_free.dias_trial > 0 else 30),
            )
        
        # Log de auditoria
        LogAuditoria.objects.create(
            usuario=user,
            tenant=tenant,
            accion=LogAuditoria.Accion.CREAR,
            descripcion="Registro de nuevo usuario",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        
        return Response({
            "message": "Usuario registrado exitosamente.",
            "user": UsuarioSerializer(user).data,
            "tenant": TenantSerializer(tenant).data,
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Inicio de sesion - retorna JWT en localStorage."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        user = serializer.validated_data["user"]
        login(request, user)
        
        user.last_login_ip = get_client_ip(request)
        user.last_login_device = request.META.get('HTTP_USER_AGENT', '')[:255]
        user.save(update_fields=['last_login_ip', 'last_login_device'])
        
        LogAuditoria.objects.create(
            usuario=user,
            tenant=user.tenant,
            accion=LogAuditoria.Accion.LOGIN,
            descripcion="Inicio de sesion exitoso",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        
        plan_name = ""
        has_plan = False
        if hasattr(user, 'tenant') and user.tenant:
            sub = user.tenant.get_active_subscription()
            if sub:
                plan_name = sub.plan.nombre
                has_plan = True
        
        initials = ""
        if user.first_name and user.last_name:
            initials = (user.first_name[0] + user.last_name[0]).upper()
        elif user.first_name:
            initials = user.first_name[:2].upper()
        else:
            initials = user.username[:2].upper()
        
        user_data = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "displayName": user.first_name if user.first_name else user.username,
            "initials": initials,
            "has_plan": has_plan,
            "plan_name": plan_name,
        }
        
        token = jwt.encode({
            "user_id": user.id,
            "exp": datetime.utcnow() + timedelta(days=7)
        }, "secret_key_placeholder", algorithm="HS256")
        
        response = Response({
            "message": "Login exitoso.",
            "user": user_data,
            "token": token,
        }, status=status.HTTP_200_OK)
        
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=request.session.session_key,
            max_age=None,
            samesite='Lax',
            httponly=False,
            secure=False,
        )
        
        return response


class LogoutView(APIView):
    """Cierre de sesion."""
    permission_classes = []  # Allow any user to call logout
    
    def post(self, request):
        if request.user.is_authenticated:
            LogAuditoria.objects.create(
                usuario=request.user,
                tenant=request.user.tenant if hasattr(request.user, 'tenant') else None,
                accion=LogAuditoria.Accion.LOGOUT,
                descripcion="Cierre de sesion",
                ip_address=get_client_ip(request),
            )
            logout(request)
        
        # Return response that clears session
        response = Response({"message": "Logout exitoso.", "success": True})
        response.delete_cookie('sessionid')
        return response


class ProfileView(APIView):
    """Perfil del usuario actual."""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        serializer = UsuarioSerializer(request.user)
        return Response(serializer.data)
    
    def put(self, request):
        serializer = UsuarioSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CambioPasswordView(APIView):
    """Cambio de password."""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = CambioPasswordSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Password actualizado exitosamente."})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para listar planes disponibles."""
    queryset = Plan.objects.filter(activo=True).order_by("orden", "precio_mensual")
    serializer_class = PlanSerializer
    permission_classes = [permissions.AllowAny]


class SuscripcionViewSet(viewsets.ModelViewSet):
    """ViewSet para gestionar suscripciones."""
    serializer_class = SuscripcionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Suscripcion.objects.none()
        if self.request.user.is_superuser:
            return Suscripcion.objects.all()
        return Suscripcion.objects.filter(tenant=self.request.user.tenant)
    
    def perform_create(self, serializer):
        if not self.request.user.is_superuser:
            serializer.save(tenant=self.request.user.tenant)
        else:
            serializer.save()
    
    @action(detail=False, methods=["get"])
    def actual(self, request):
        """Obtiene la suscripcion activa del tenant actual."""
        if not request.user.tenant:
            return Response({"detail": "Usuario sin tenant."}, status=status.HTTP_400_BAD_REQUEST)
        
        sub = request.user.tenant.get_active_subscription()
        if sub:
            return Response(SuscripcionSerializer(sub).data)
        return Response({"detail": "Sin suscripcion activa."}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=False, methods=["post"])
    def cambiar_plan(self, request):
        """Cambia el plan del tenant actual. Acepta plan_id o plan_slug."""
        if not request.user.tenant:
            return Response({"detail": "Usuario sin tenant."}, status=status.HTTP_400_BAD_REQUEST)
        
        plan_id = request.data.get("plan_id")
        plan_slug = request.data.get("plan_slug")
        periodicidad = request.data.get("periodicidad", Plan.Periodicidad.MENSUAL)
        
        if plan_slug:
            try:
                plan = Plan.objects.get(slug=plan_slug, activo=True)
            except Plan.DoesNotExist:
                return Response({"detail": "Plan no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        elif plan_id:
            try:
                plan = Plan.objects.get(id=plan_id, activo=True)
            except Plan.DoesNotExist:
                return Response({"detail": "Plan no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({"detail": "Se requiere plan_id o plan_slug."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Cancelar suscripcion actual
        sub_actual = request.user.tenant.get_active_subscription()
        if sub_actual:
            sub_actual.estado = Suscripcion.Estado.CANCELADA
            sub_actual.fecha_cancelacion = timezone.now()
            sub_actual.save()
        
        # Crear nueva suscripcion
        estado = (
            Suscripcion.Estado.ACTIVA
            if plan.tipo == Plan.TipoPlan.FREE
            else Suscripcion.Estado.PENDIENTE
        )
        nueva_sub = Suscripcion.objects.create(
            tenant=request.user.tenant,
            plan=plan,
            estado=estado,
            periodicidad=periodicidad,
        )
        
        # Log de auditoria
        LogAuditoria.objects.create(
            usuario=request.user,
            tenant=request.user.tenant,
            accion=LogAuditoria.Accion.CAMBIO_PLAN,
            descripcion=f"Cambio de plan a {plan.nombre}",
            datos_extra={"plan_id": plan.id, "plan_nombre": plan.nombre},
        )
        
        return Response(SuscripcionSerializer(nueva_sub).data, status=status.HTTP_201_CREATED)


class TenantViewSet(viewsets.ModelViewSet):
    """ViewSet para gestionar tenants (solo superusers)."""
    queryset = Tenant.objects.all()
    serializer_class = TenantSerializer
    
    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]
    
    @action(detail=True, methods=["get"])
    def estadisticas(self, request, pk=None):
        """Obtiene estadisticas del tenant."""
        tenant = self.get_object()
        
        trades_count = 0
        trades_today = 0
        
        # Obtener cuentas del tenant si tiene relacion
        if hasattr(tenant, 'cuentas'):
            from gestion_riesgo.models import OperacionDeriv
            cuenta_ids = tenant.cuentas.values_list('id', flat=True)
            trades_count = OperacionDeriv.objects.filter(cuenta_id__in=cuenta_ids).count()
            
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            trades_today = OperacionDeriv.objects.filter(
                cuenta_id__in=cuenta_ids,
                updated_at__gte=today_start
            ).count()
        
        sub = tenant.get_active_subscription()
        
        return Response({
            "tenant": TenantSerializer(tenant).data,
            "suscripcion": SuscripcionSerializer(sub).data if sub else None,
            "estadisticas": {
                "trades_totales": trades_count,
                "trades_hoy": trades_today,
                "usuarios_count": tenant.usuarios.count(),
            }
        })


class MeViewSet(viewsets.ViewSet):
    """ViewSet para el usuario actual (perfil)."""
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        return Response(UsuarioSerializer(request.user).data)

    def partial_update(self, request, pk=None):
        return self._update(request)

    def update(self, request, pk=None):
        return self._update(request)

    def _update(self, request):
        user = request.user
        first_name = request.data.get("first_name")
        last_name = request.data.get("last_name")
        telefono = request.data.get("telefono")

        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        user.save(update_fields=['first_name', 'last_name'])

        if telefono is not None and user.tenant:
            user.tenant.telefono = telefono
            user.tenant.save(update_fields=['telefono'])

        return Response(UsuarioSerializer(user).data)


class LogAuditoriaViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para logs de auditoria."""
    serializer_class = LogAuditoriaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return LogAuditoria.objects.none()
        if self.request.user.is_superuser:
            return LogAuditoria.objects.all()
        return LogAuditoria.objects.filter(tenant=self.request.user.tenant)
    
    @action(detail=False, methods=["get"])
    def ultimos(self, request):
        """Obtiene los ultimos 50 logs."""
        logs = self.get_queryset()[:50]
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def health_check(request):
    """Health check para el API."""
    return Response({
        "status": "ok",
        "timestamp": timezone.now().isoformat(),
    })
