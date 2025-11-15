from django.contrib import admin

from .models import CooldownActivo, IndicadoresActivo, RendimientoActivo, TickCache


@admin.register(TickCache)
class TickCacheAdmin(admin.ModelAdmin):
    list_display = ("activo", "precio", "epoch", "timestamp")
    list_filter = ("activo", "timestamp")
    search_fields = ("activo__nombre",)
    ordering = ("-timestamp",)
    readonly_fields = ("timestamp",)


@admin.register(IndicadoresActivo)
class IndicadoresActivoAdmin(admin.ModelAdmin):
    list_display = (
        "activo",
        "score_total",
        "momentum_pct",
        "volatilidad",
        "consistencia",
        "direccion_sugerida",
        "calculado_en",
    )
    list_filter = ("direccion_sugerida", "calculado_en")
    search_fields = ("activo__nombre",)
    ordering = ("-score_total",)
    readonly_fields = (
        "momentum_simple",
        "momentum_pct",
        "volatilidad",
        "tendencia_ema",
        "precio_actual",
        "rate_of_change",
        "fuerza_movimiento",
        "consistencia",
        "score_total",
        "calculado_en",
    )
    fieldsets = (
        (
            "Activo",
            {
                "fields": ("activo",),
            },
        ),
        (
            "Indicadores de Momentum",
            {
                "fields": ("momentum_simple", "momentum_pct"),
            },
        ),
        (
            "Volatilidad y Tendencia",
            {
                "fields": ("volatilidad", "tendencia_ema", "precio_actual"),
            },
        ),
        (
            "Análisis Avanzado",
            {
                "fields": ("rate_of_change", "fuerza_movimiento", "consistencia"),
            },
        ),
        (
            "Score y Dirección",
            {
                "fields": ("score_total", "direccion_sugerida", "ticks_analizados"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("calculado_en",),
            },
        ),
    )


@admin.register(RendimientoActivo)
class RendimientoActivoAdmin(admin.ModelAdmin):
    list_display = (
        "activo",
        "hora",
        "winrate_dinamico",
        "total_operaciones",
        "operaciones_ganadas",
        "operaciones_perdidas",
        "beneficio_total",
        "actualizado_en",
    )
    list_filter = ("hora", "actualizado_en")
    search_fields = ("activo__nombre",)
    ordering = ("-winrate_dinamico",)
    readonly_fields = (
        "winrate_dinamico",
        "total_operaciones",
        "operaciones_ganadas",
        "operaciones_perdidas",
        "beneficio_total",
        "perdida_total",
        "drawdown_maximo",
        "drawdown_actual",
        "actualizado_en",
    )
    fieldsets = (
        (
            "Activo y Horario",
            {
                "fields": ("activo", "hora"),
            },
        ),
        (
            "Estadísticas",
            {
                "fields": (
                    "winrate_dinamico",
                    "total_operaciones",
                    "operaciones_ganadas",
                    "operaciones_perdidas",
                ),
            },
        ),
        (
            "Beneficios y Pérdidas",
            {
                "fields": ("beneficio_total", "perdida_total"),
            },
        ),
        (
            "Drawdown",
            {
                "fields": ("drawdown_maximo", "drawdown_actual"),
            },
        ),
        (
            "Período",
            {
                "fields": ("periodo_desde", "periodo_hasta"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("actualizado_en",),
            },
        ),
    )


@admin.register(CooldownActivo)
class CooldownActivoAdmin(admin.ModelAdmin):
    list_display = ("activo", "motivo", "finaliza_en", "creado_en", "esta_activo")
    list_filter = ("finaliza_en", "creado_en")
    search_fields = ("activo__nombre", "motivo")
    ordering = ("-finaliza_en",)
    readonly_fields = ("creado_en",)
    
    def save_model(self, request, obj, form, change):
        """Valida y trunca el motivo antes de guardar."""
        if obj.motivo and len(obj.motivo) > 40:
            obj.motivo = obj.motivo[:40]
        super().save_model(request, obj, form, change)
