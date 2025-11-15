from django.contrib import admin

from .models import AjusteBalance, Operacion, Tick


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


@admin.register(AjusteBalance)
class AjusteBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "detectado_en",
        "balance_real",
        "balance_esperado",
        "diferencia",
        "balance_anterior",
    )
    list_filter = ("detectado_en",)
    search_fields = ("descripcion",)
    ordering = ("-detectado_en",)
    readonly_fields = (
        "balance_esperado",
        "balance_real",
        "diferencia",
        "detectado_en",
        "balance_anterior",
    )
    fieldsets = (
        (
            "Información de Balance",
            {
                "fields": (
                    "balance_real",
                    "balance_esperado",
                    "diferencia",
                    "balance_anterior",
                )
            },
        ),
        ("Detalles", {"fields": ("descripcion", "detectado_en")}),
    )
