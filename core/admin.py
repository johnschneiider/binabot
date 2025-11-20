from django.contrib import admin

from .models import ActivoPermitido, ConfiguracionBot


@admin.register(ConfiguracionBot)
class ConfiguracionBotAdmin(admin.ModelAdmin):
    list_display = (
        "balance_actual",
        "stop_loss_actual",
        "estado",
        "modo_inverso",
        "activo_seleccionado",
        "ultima_actualizacion",
    )
    readonly_fields = (
        "stop_loss_actual",
        "ultima_actualizacion",
        "pausado_desde",
        "pausa_finaliza",
    )
    fieldsets = (
        ("Estado", {
            "fields": ("estado", "balance_actual", "stop_loss_actual", "en_operacion", "activo_seleccionado")
        }),
        ("Configuración", {
            "fields": ("modo_inverso",)
        }),
        ("Estadísticas", {
            "fields": ("ganancia_acumulada", "perdida_acumulada", "balance_meta_base", "balance_stop_loss_base")
        }),
        ("Pausas", {
            "fields": ("pausado_desde", "pausa_finaliza", "mejor_horario", "ultima_simulacion")
        }),
    )


@admin.register(ActivoPermitido)
class ActivoPermitidoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "habilitado", "actualizado")
    list_filter = ("habilitado",)
    search_fields = ("nombre",)
