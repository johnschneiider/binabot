from django.contrib import admin
from .models import OperacionInversa, ConfiguracionBotInverso


@admin.register(OperacionInversa)
class OperacionInversaAdmin(admin.ModelAdmin):
    list_display = [
        "numero_contrato",
        "activo",
        "direccion",
        "resultado",
        "beneficio",
        "monto_invertido",
        "hora_inicio",
        "operacion_principal_id",
    ]
    list_filter = ["resultado", "direccion", "activo", "es_simulada"]
    search_fields = ["numero_contrato", "activo", "operacion_principal_id"]
    readonly_fields = ["creado", "actualizado"]
    ordering = ["-hora_inicio"]


@admin.register(ConfiguracionBotInverso)
class ConfiguracionBotInversoAdmin(admin.ModelAdmin):
    list_display = [
        "balance_actual",
        "estado",
        "stop_loss_actual",
        "ganancia_acumulada",
        "perdida_acumulada",
        "activo_seleccionado",
        "en_operacion",
    ]
    readonly_fields = ["ultima_actualizacion"]

