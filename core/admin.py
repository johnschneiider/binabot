from django.contrib import admin

from .models import ActivoPermitido, ConfiguracionBot


@admin.register(ConfiguracionBot)
class ConfiguracionBotAdmin(admin.ModelAdmin):
    list_display = (
        "balance_actual",
        "meta_actual",
        "stop_loss_actual",
        "estado",
        "activo_seleccionado",
        "ultima_actualizacion",
    )
    readonly_fields = (
        "meta_actual",
        "stop_loss_actual",
        "ultima_actualizacion",
        "pausado_desde",
        "pausa_finaliza",
    )


@admin.register(ActivoPermitido)
class ActivoPermitidoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "habilitado", "actualizado")
    list_filter = ("habilitado",)
    search_fields = ("nombre",)
