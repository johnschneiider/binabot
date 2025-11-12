from django.contrib import admin

from .models import Operacion, Tick


@admin.register(Operacion)
class OperacionAdmin(admin.ModelAdmin):
    list_display = (
        "numero_contrato",
        "activo",
        "direccion",
        "resultado",
        "es_simulada",
        "monto_invertido",
        "beneficio",
        "hora_inicio",
        "hora_fin",
    )
    list_filter = ("es_simulada", "direccion", "resultado", "activo")
    search_fields = ("numero_contrato", "activo")
    readonly_fields = ("creado", "actualizado")


@admin.register(Tick)
class TickAdmin(admin.ModelAdmin):
    list_display = ("activo", "epoch", "precio", "pip_size", "recibido")
    list_filter = ("activo",)
    search_fields = ("activo",)
    ordering = ("-epoch",)
    readonly_fields = ("datos", "recibido")
