from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import Tenant, Plan, Suscripcion, Usuario, LogAuditoria


class TenantSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Tenant."""
    
    class Meta:
        model = Tenant
        fields = [
            "id", "nombre", "slug", "email", "telefono",
            "estado", "fecha_creacion", "fecha_expiracion_trial",
            "max_cuentas_deriv", "max_symbols", "permite_api"
        ]
        read_only_fields = ["id", "fecha_creacion"]


class PlanSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Plan."""
    
    precio_formatted = serializers.SerializerMethodField()
    
    class Meta:
        model = Plan
        fields = [
            "id", "nombre", "slug", "tipo",
            "max_cuentas_deriv", "max_symbols",
            "permite_backtest", "permite_api", "permite_white_label",
            "soporte_prioritario", "max_trades_dia", "max_ticks_por_dia",
            "precio_mensual", "precio_trimestral", "precio_anual",
            "precio_formatted", "activo", "dias_trial", "descripcion"
        ]
    
    def get_precio_formatted(self, obj) -> dict:
        return {
            "mensual": f"${obj.precio_mensual}",
            "trimestral": f"${obj.precio_trimestral}",
            "anual": f"${obj.precio_anual}",
        }


class SuscripcionSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Suscripcion."""
    
    plan_detallado = PlanSerializer(source="plan", read_only=True)
    tenant_nombre = serializers.CharField(source="tenant.nombre", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    dias_restantes = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Suscripcion
        fields = [
            "id", "tenant", "tenant_nombre", "plan", "plan_detallado",
            "estado", "periodicidad",
            "fecha_inicio", "fecha_expiracion", "fecha_cancelacion",
            "stripe_subscription_id", "stripe_customer_id",
            "is_active", "dias_restantes", "notas"
        ]
        read_only_fields = ["id", "stripe_subscription_id", "stripe_customer_id"]


class UsuarioSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Usuario."""
    
    tenant_nombre = serializers.CharField(source="tenant.nombre", read_only=True)
    can_trade = serializers.BooleanField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Usuario
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "tenant", "tenant_nombre", "tipo",
            "puede_operar", "puede_configurar", "puede_ver_reportes",
            "timezone", "tema", "last_login",
            "can_trade", "is_active", "is_superuser"
        ]
        read_only_fields = [
            "id", "last_login", "can_trade", "is_active", "is_superuser"
        ]


class UsuarioCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear usuarios."""
    
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = Usuario
        fields = [
            "username", "email", "password", "password_confirm",
            "first_name", "last_name"
        ]
    
    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({
                "password_confirm": "Las contrasenas no coinciden."
            })
        return attrs
    
    def create(self, validated_data):
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = Usuario(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer para login."""
    
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")
        
        user = authenticate(username=username, password=password)
        
        if not user:
            raise serializers.ValidationError("Credenciales invalidas.")
        
        if not user.is_active:
            raise serializers.ValidationError("Usuario inactivo.")
        
        attrs["user"] = user
        return attrs


class CambioPasswordSerializer(serializers.Serializer):
    """Serializer para cambiar password."""
    
    password_actual = serializers.CharField(write_only=True)
    password_nueva = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        user = self.context["request"].user
        
        if not user.check_password(attrs["password_actual"]):
            raise serializers.ValidationError({
                "password_actual": "Contrasena actual incorrecta."
            })
        
        if attrs["password_nueva"] != attrs["password_confirm"]:
            raise serializers.ValidationError({
                "password_confirm": "Las contrasenas no coinciden."
            })
        
        return attrs
    
    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["password_nueva"])
        user.save()
        return user


class LogAuditoriaSerializer(serializers.ModelSerializer):
    """Serializer para log de auditoria."""
    
    usuario_username = serializers.CharField(source="usuario.username", read_only=True)
    
    class Meta:
        model = LogAuditoria
        fields = [
            "id", "usuario", "usuario_username", "tenant",
            "accion", "descripcion", "ip_address", "user_agent",
            "datos_extra", "timestamp"
        ]
        read_only_fields = ["id", "timestamp"]
