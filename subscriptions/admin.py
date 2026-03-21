from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Tenant, Plan, Suscripcion, Usuario, LogAuditoria


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["nombre", "email", "estado", "fecha_creacion", "get_suscripcion_activa"]
    list_filter = ["estado", "fecha_creacion"]
    search_fields = ["nombre", "email", "slug"]
    readonly_fields = ["id", "fecha_creacion"]
    ordering = ["-fecha_creacion"]
    
    def get_suscripcion_activa(self, obj):
        sub = obj.get_active_subscription()
        return sub.plan.nombre if sub else "Sin suscripcion"
    get_suscripcion_activa.short_description = "Suscripcion"


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo", "precio_mensual", "precio_trimestral", "precio_anual", "activo", "orden"]
    list_filter = ["tipo", "activo"]
    search_fields = ["nombre", "slug"]
    readonly_fields = ["id"]
    ordering = ["orden", "precio_mensual"]


@admin.register(Suscripcion)
class SuscripcionAdmin(admin.ModelAdmin):
    list_display = ["tenant", "plan", "estado", "periodicidad", "fecha_inicio", "fecha_expiracion", "is_active"]
    list_filter = ["estado", "periodicidad", "plan"]
    search_fields = ["tenant__nombre", "tenant__email"]
    readonly_fields = ["id", "is_active", "dias_restantes"]
    raw_id_fields = ["tenant", "plan"]
    ordering = ["-fecha_inicio"]
    
    actions = ["activar_suscripcion", "cancelar_suscripcion"]
    
    def activar_suscripcion(self, request, queryset):
        for sub in queryset:
            sub.estado = sub.Estado.ACTIVA
            sub.fecha_inicio = sub.fecha_inicio or request.admin_date.now()
            if not sub.fecha_expiracion:
                from datetime import timedelta
                sub.fecha_expiracion = request.admin_date.now() + timedelta(days=30)
            sub.save()
        self.message_user(request, f"{queryset.count()} suscripciones activadas.")
    activar_suscripcion.short_description = "Activar suscripciones seleccionadas"
    
    def cancelar_suscripcion(self, request, queryset):
        queryset.update(
            estado=Suscripcion.Estado.CANCELADA,
            fecha_cancelacion=request.admin_date.now()
        )
        self.message_user(request, f"{queryset.count()} suscripciones canceladas.")
    cancelar_suscripcion.short_description = "Cancelar suscripciones seleccionadas"


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ["username", "email", "tenant", "tipo", "is_active", "last_login", "can_trade"]
    list_filter = ["tipo", "is_active", "is_superuser", "tenant__estado"]
    search_fields = ["username", "email", "first_name", "last_name"]
    readonly_fields = ["id", "last_login", "last_login_ip", "last_login_device"]
    
    fieldsets = UserAdmin.fieldsets + (
        ("Multi-tenant", {"fields": ("tenant", "tipo")}),
        ("Permisos", {"fields": ("puede_operar", "puede_configurar", "puede_ver_reportes")}),
        ("Preferencias", {"fields": ("timezone", "tema")}),
        ("Auditoria", {"fields": ("last_login_ip", "last_login_device")}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Multi-tenant", {"fields": ("tenant", "tipo")}),
    )
    
    def can_trade(self, obj):
        return obj.can_trade
    can_trade.boolean = True
    can_trade.short_description = "Puede tradear"


@admin.register(LogAuditoria)
class LogAuditoriaAdmin(admin.ModelAdmin):
    list_display = ["usuario", "tenant", "accion", "descripcion", "ip_address", "timestamp"]
    list_filter = ["accion", "timestamp"]
    search_fields = ["usuario__username", "descripcion", "ip_address"]
    readonly_fields = ["id", "usuario", "tenant", "accion", "descripcion", "ip_address", "user_agent", "datos_extra", "timestamp"]
    ordering = ["-timestamp"]
    has_add_permission = False
    has_change_permission = False
