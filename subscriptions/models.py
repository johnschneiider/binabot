from __future__ import annotations

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.conf import settings
import uuid


class Tenant(models.Model):
    """
    Tenant (Cliente) - Cada cliente tiene su propio espacio.
    
    El tenant identifica la organizacion/cuenta del cliente.
    Todos los datos del cliente estan asociados a su tenant.
    """
    
    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        SUSPENIDO = "SUSPENDIDO", "Suspendido"
        CANCELADO = "CANCELADO", "Cancelado"
        TRIAL = "TRIAL", "Prueba gratuita"
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    
    email = models.EmailField(unique=True)
    telefono = models.CharField(max_length=20, blank=True)
    
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.TRIAL)
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_expiracion_trial = models.DateTimeField(null=True, blank=True)
    
    max_cuentas_deriv = models.IntegerField(default=1)
    max_symbols = models.IntegerField(default=3)
    permite_api = models.BooleanField(default=False)
    
    notas = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = "tenants"
        ordering = ["-fecha_creacion"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["email"]),
            models.Index(fields=["estado"]),
        ]
    
    def __str__(self) -> str:
        return f"{self.nombre} ({self.estado})"
    
    @property
    def is_active(self) -> bool:
        return self.estado in [self.Estado.ACTIVO, self.Estado.TRIAL]
    
    def get_active_subscription(self):
        return self.suscripciones.filter(
            estado__in=[Suscripcion.Estado.ACTIVA, Suscripcion.Estado.TRIAL]
        ).first()


class Plan(models.Model):
    """
    Plan de suscripcion - Define los tiers de servicio.
    """
    
    class TipoPlan(models.TextChoices):
        FREE = "FREE", "Gratis"
        BASICO = "BASICO", "Basico"
        PRO = "PRO", "Profesional"
        INSTITUCIONAL = "INSTITUCIONAL", "Institucional"
    
    class Periodicidad(models.TextChoices):
        MENSUAL = "MENSUAL", "Mensual"
        TRIMESTRAL = "TRIMESTRAL", "Trimestral"
        ANUAL = "ANUAL", "Anual"
    
    nombre = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True)
    tipo = models.CharField(max_length=20, choices=TipoPlan.choices, default=TipoPlan.BASICO)
    
    max_cuentas_deriv = models.IntegerField(default=1)
    max_symbols = models.IntegerField(default=1)
    permite_backtest = models.BooleanField(default=False)
    permite_api = models.BooleanField(default=False)
    permite_white_label = models.BooleanField(default=False)
    soporte_prioritario = models.BooleanField(default=False)
    
    max_trades_dia = models.IntegerField(default=50)
    max_ticks_por_dia = models.IntegerField(default=10000)
    
    precio_mensual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_trimestral = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_anual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    activo = models.BooleanField(default=True)
    orden = models.IntegerField(default=0)
    dias_trial = models.IntegerField(default=0)
    descripcion = models.TextField(blank=True)
    
    class Meta:
        db_table = "plans"
        ordering = ["orden", "precio_mensual"]
    
    def __str__(self) -> str:
        return f"{self.nombre} - ${self.precio_mensual}/mes"
    
    def get_precio(self, periodicidad: str = Periodicidad.MENSUAL) -> float:
        if periodicidad == self.Periodicidad.MENSUAL:
            return float(self.precio_mensual)
        elif periodicidad == self.Periodicidad.TRIMESTRAL:
            return float(self.precio_trimestral)
        elif periodicidad == self.Periodicidad.ANUAL:
            return float(self.precio_anual)
        return 0


class Suscripcion(models.Model):
    """
    Suscripcion activa de un tenant a un plan.
    """
    
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        CANCELADA = "CANCELADA", "Cancelada"
        EXPIRADA = "EXPIRADA", "Expirada"
        TRIAL = "TRIAL", "Prueba gratuita"
        PENDIENTE = "PENDIENTE", "Pendiente de pago"
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="suscripciones")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="suscripciones")
    
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    
    periodicidad = models.CharField(
        max_length=20, 
        choices=Plan.Periodicidad.choices, 
        default=Plan.Periodicidad.MENSUAL
    )
    
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_expiracion = models.DateTimeField(null=True, blank=True)
    fecha_cancelacion = models.DateTimeField(null=True, blank=True)
    
    stripe_subscription_id = models.CharField(max_length=100, blank=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True)
    
    notas = models.TextField(blank=True)
    
    class Meta:
        db_table = "subscriptions"
        ordering = ["-fecha_inicio"]
        indexes = [
            models.Index(fields=["tenant", "estado"]),
            models.Index(fields=["fecha_expiracion"]),
        ]
    
    def __str__(self) -> str:
        return f"{self.tenant.nombre} - {self.plan.nombre} ({self.estado})"
    
    @property
    def is_active(self) -> bool:
        if self.estado == self.Estado.TRIAL:
            return self.fecha_expiracion and self.fecha_expiracion > timezone.now()
        if self.estado == self.Estado.ACTIVA:
            return self.fecha_expiracion and self.fecha_expiracion > timezone.now()
        return False
    
    @property
    def dias_restantes(self) -> int:
        if not self.fecha_expiracion:
            return 0
        delta = self.fecha_expiracion - timezone.now()
        return max(0, delta.days)


class Usuario(AbstractUser):
    """
    Usuario extiende el modelo de Django con informacion multi-tenant.
    """
    
    class TipoUsuario(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Super Administrador"
        ADMIN_TENANT = "ADMIN_TENANT", "Administrador Tenant"
        OPERADOR = "OPERADOR", "Operador"
        VIEWER = "VIEWER", "Solo lectura"
    
    tenant = models.ForeignKey(
        Tenant, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="usuarios"
    )
    
    tipo = models.CharField(
        max_length=20, 
        choices=TipoUsuario.choices, 
        default=TipoUsuario.OPERADOR
    )
    
    puede_operar = models.BooleanField(default=True)
    puede_configurar = models.BooleanField(default=False)
    puede_ver_reportes = models.BooleanField(default=True)
    
    timezone = models.CharField(max_length=50, default="America/Bogota")
    tema = models.CharField(max_length=20, default="light")
    
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_device = models.CharField(max_length=255, blank=True)
    
    class Meta:
        db_table = "users"
    
    def __str__(self) -> str:
        return f"{self.username} ({self.tipo})"
    
    @property
    def is_admin_tenant(self) -> bool:
        return self.tipo == self.TipoUsuario.ADMIN_TENANT or self.is_superuser
    
    @property
    def can_trade(self) -> bool:
        if not self.puede_operar:
            return False
        if not self.tenant or not self.tenant.is_active:
            return False
        sub = self.tenant.get_active_subscription()
        return sub and sub.is_active


class LogAuditoria(models.Model):
    """
    Log de auditoria para compliance y seguridad.
    """
    
    class Accion(models.TextChoices):
        LOGIN = "LOGIN", "Inicio de sesion"
        LOGOUT = "LOGOUT", "Cierre de sesion"
        LOGIN_FAILED = "LOGIN_FAILED", "Login fallido"
        CREAR = "CREAR", "Crear registro"
        ACTUALIZAR = "ACTUALIZAR", "Actualizar registro"
        ELIMINAR = "ELIMINAR", "Eliminar registro"
        TRADING = "TRADING", "Operacion de trading"
        CAMBIO_PLAN = "CAMBIO_PLAN", "Cambio de plan"
        ERROR = "ERROR", "Error del sistema"
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name="logs_auditoria"
    )
    tenant = models.ForeignKey(
        Tenant, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name="logs_auditoria"
    )
    
    accion = models.CharField(max_length=20, choices=Accion.choices)
    descripcion = models.CharField(max_length=500)
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    
    datos_extra = models.JSONField(default=dict, blank=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = "audit_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["usuario", "-timestamp"]),
            models.Index(fields=["tenant", "-timestamp"]),
            models.Index(fields=["accion", "-timestamp"]),
        ]
    
    def __str__(self) -> str:
        return f"{self.usuario} - {self.accion} - {self.timestamp}"
