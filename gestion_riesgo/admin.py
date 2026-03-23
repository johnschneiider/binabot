from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.contrib.auth import get_user_model
from .models import Deposito, Retiro, Inversionista, RendimientoFondo, Cuenta, GrupoAcceso

User = get_user_model()


@admin.action(description="Aprobar depósitos seleccionados")
def approve_deposits(modeladmin, request, queryset):
    count = 0
    for dep in queryset.filter(estado=Deposito.Estado.PENDIENTE):
        inv = dep.inversionista
        inv.capital_actual = float(inv.capital_actual) + dep.monto
        inv.capital_inicial = float(inv.capital_inicial) + dep.monto
        inv.save()
        dep.estado = Deposito.Estado.CONFIRMADO
        dep.fecha_confirmado = timezone.now()
        dep.notas = (dep.notas + f" | Aprobado por {request.user.username}").strip()
        dep.save()
        count += 1
    messages.success(request, f"{count} depósito(s) aprobado(s) y capital acreditado.")


@admin.action(description="Rechazar depósitos seleccionados")
def reject_deposits(modeladmin, request, queryset):
    count = 0
    for dep in queryset.filter(estado=Deposito.Estado.PENDIENTE):
        dep.estado = Deposito.Estado.RECHAZADO
        dep.notas = (dep.notas + f" | Rechazado por {request.user.username}").strip()
        dep.save()
        count += 1
    messages.success(request, f"{count} depósito(s) rechazado(s).")


@admin.register(Deposito)
class DepositoAdmin(admin.ModelAdmin):
    list_display = ("id", "inversionista_link", "monto_display", "estado_badge", "referencia", "fecha_creado", "fecha_confirmado")
    list_filter = ("estado", "fecha_creado")
    search_fields = ("inversionista__user__username", "inversionista__user__email", "referencia")
    readonly_fields = ("inversionista", "monto", "referencia", "fecha_creado")
    actions = [approve_deposits, reject_deposits]
    list_per_page = 30

    def inversionista_link(self, obj):
        return format_html(
            '<a href="/admin/auth/user/{}/change/">{}</a>',
            obj.inversionista.user.id,
            obj.inversionista.user.username,
        )
    inversionista_link.short_description = "Inversionista"

    def monto_display(self, obj):
        return format_html("<b>${:.2f} USD</b>", obj.monto)
    monto_display.short_description = "Monto"

    def estado_badge(self, obj):
        colors = {
            Deposito.Estado.PENDIENTE: "#f59e0b",
            Deposito.Estado.CONFIRMADO: "#10b981",
            Deposito.Estado.RECHAZADO: "#ef4444",
            Deposito.Estado.CANCELADO: "#6b7280",
        }
        color = colors.get(obj.estado, "#6b7280")
        return format_html(
            '<span style="background:{}22;color:{};padding:3px 10px;border-radius:100px;font-size:11px;font-weight:700;">{}</span>',
            color, color, obj.get_estado_display(),
        )
    estado_badge.short_description = "Estado"

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("inversionista__user")


@admin.action(description="Aprobar retiros seleccionados")
def approve_withdrawals(modeladmin, request, queryset):
    count = 0
    for ret in queryset.filter(estado=Retiro.Estado.SOLICITADO):
        ret.estado = Retiro.Estado.EN_PROCESO
        ret.notas_admin = f"Aprobado por {request.user.username}"
        ret.fecha_proceso = timezone.now()
        ret.save()
        count += 1
    messages.success(request, f"{count} retiro(s) aprobado(s) — ahora en proceso.")


@admin.action(description="Completar retiros seleccionados")
def complete_withdrawals(modeladmin, request, queryset):
    count = 0
    for ret in queryset.filter(estado=Retiro.Estado.EN_PROCESO):
        ret.estado = Retiro.Estado.COMPLETADO
        ret.fecha_proceso = timezone.now()
        ret.save()
        count += 1
    messages.success(request, f"{count} retiro(s) marcado(s) como completado.")


@admin.action(description="Rechazar retiros seleccionados")
def reject_withdrawals(modeladmin, request, queryset):
    count = 0
    for ret in queryset.filter(estado__in=[Retiro.Estado.SOLICITADO, Retiro.Estado.EN_PROCESO]):
        ret.estado = Retiro.Estado.RECHAZADO
        ret.notas_admin = (ret.notas_admin + f" | Rechazado por {request.user.username}").strip()
        inv = ret.inversionista
        inv.capital_actual = float(inv.capital_actual) + ret.monto
        inv.save()
        ret.save()
        count += 1
    messages.warning(request, f"{count} retiro(s) rechazado(s). El capital fue reintegrado al inversionista.")


@admin.register(Retiro)
class RetiroAdmin(admin.ModelAdmin):
    list_display = ("id", "inversionista_link", "monto_display", "estado_badge", "destino", "fecha_solicitud", "fecha_proceso")
    list_filter = ("estado", "fecha_solicitud")
    search_fields = ("inversionista__user__username", "inversionista__user__email", "destino")
    readonly_fields = ("inversionista", "monto", "fecha_solicitud")
    actions = [approve_withdrawals, complete_withdrawals, reject_withdrawals]
    list_per_page = 30

    def inversionista_link(self, obj):
        return format_html(
            '<a href="/admin/auth/user/{}/change/">{}</a>',
            obj.inversionista.user.id,
            obj.inversionista.user.username,
        )
    inversionista_link.short_description = "Inversionista"

    def monto_display(self, obj):
        return format_html("<b>${:.2f} USD</b>", obj.monto)
    monto_display.short_description = "Monto"

    def estado_badge(self, obj):
        colors = {
            Retiro.Estado.SOLICITADO: "#f59e0b",
            Retiro.Estado.EN_PROCESO: "#3b82f6",
            Retiro.Estado.COMPLETADO: "#10b981",
            Retiro.Estado.RECHAZADO: "#ef4444",
        }
        color = colors.get(obj.estado, "#6b7280")
        return format_html(
            '<span style="background:{}22;color:{};padding:3px 10px;border-radius:100px;font-size:11px;font-weight:700;">{}</span>',
            color, color, obj.get_estado_display(),
        )
    estado_badge.short_description = "Estado"

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("inversionista__user")


@admin.register(Inversionista)
class InversionistaAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "email", "capital_actual_display", "capital_inicial_display", "ganancia_display", "fecha_registro")
    search_fields = ("user__username", "user__email", "nombre")
    list_per_page = 30

    def username(self, obj):
        return obj.user.username
    username.short_description = "Usuario"

    def email(self, obj):
        return obj.user.email
    email.short_description = "Email"

    def capital_actual_display(self, obj):
        return f"${obj.capital_actual:,.2f}"
    capital_actual_display.short_description = "Capital actual"

    def capital_inicial_display(self, obj):
        return f"${obj.capital_inicial:,.2f}"
    capital_inicial_display.short_description = "Capital invertido"

    def ganancia_display(self, obj):
        color = "#10b981" if obj.ganancia_acumulada >= 0 else "#ef4444"
        return format_html("<b style='color:{}'>${:,.2f}</b>", color, obj.ganancia_acumulada)
    ganancia_display.short_description = "Ganancia acumulada"

    def fecha_registro(self, obj):
        return obj.user.date_joined.strftime("%d %b %Y")
    fecha_registro.short_description = "Registrado"


@admin.register(RendimientoFondo)
class RendimientoFondoAdmin(admin.ModelAdmin):
    list_display = ("anno", "mes", "balance_display", "ganancia_display", "rendimiento_display", "winrate_display")
    list_filter = ("anno",)
    ordering = ("-anno", "-mes")

    def balance_display(self, obj):
        return f"${obj.balance_fin:,.2f}"
    balance_display.short_description = "Balance fin"

    def ganancia_display(self, obj):
        return f"${obj.ganancia:,.2f}"
    ganancia_display.short_description = "Ganancia"

    def rendimiento_display(self, obj):
        color = "#10b981" if obj.rendimiento_pct >= 0 else "#ef4444"
        return format_html("<b style='color:{}'>{:+.2f}%</b>", color, obj.rendimiento_pct)
    rendimiento_display.short_description = "Rendimiento"

    def winrate_display(self, obj):
        return f"{obj.winrate:.1f}%"
    winrate_display.short_description = "Winrate"


@admin.register(GrupoAcceso)
class GrupoAccesoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "usuarios_count", "urls_count", "fecha_creado", "creado_por_link")
    search_fields = ("nombre",)
    filter_horizontal = ("usuarios",)
    list_per_page = 30

    def usuarios_count(self, obj):
        return obj.usuarios.count()
    usuarios_count.short_description = "Usuarios"

    def urls_count(self, obj):
        return len(obj.get_urls_list())
    urls_count.short_description = "Rutas"

    def creado_por_link(self, obj):
        if obj.creado_por:
            return format_html(
                '<a href="/admin/auth/user/{}/change/">{}</a>',
                obj.creado_por.id,
                obj.creado_por.username,
            )
        return "—"
    creado_por_link.short_description = "Creado por"

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ["creado_por"]
        return ["creado_por", "usuarios"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

