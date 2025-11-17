from django.contrib import admin
from .models import EstrategiaGenetica, PoblacionGenetica, EvaluacionEstrategia, EntrenamientoIA


@admin.register(EstrategiaGenetica)
class EstrategiaGeneticaAdmin(admin.ModelAdmin):
    list_display = [
        'nombre', 'generacion', 'fitness', 'winrate', 'beneficio_total',
        'operaciones_evaluadas', 'activa', 'ultima_evaluacion'
    ]
    list_filter = ['activa', 'generacion', 'ultima_evaluacion']
    search_fields = ['nombre', 'descripcion']
    readonly_fields = [
        'fitness', 'winrate', 'operaciones_evaluadas', 'ganadas', 'perdidas',
        'beneficio_total', 'sharpe_ratio', 'creada', 'actualizada', 'ultima_evaluacion'
    ]
    fieldsets = (
        ('Información básica', {
            'fields': ('nombre', 'descripcion', 'activa', 'generacion')
        }),
        ('Parámetros genéticos', {
            'fields': (
                'umbral_variacion_min', 'umbral_confianza_min', 'ventana_ticks',
                'peso_winrate_simulacion', 'peso_confianza_horario', 'umbral_riesgo_max'
            )
        }),
        ('Métricas de rendimiento', {
            'fields': (
                'fitness', 'operaciones_evaluadas', 'ganadas', 'perdidas', 'winrate',
                'beneficio_total', 'sharpe_ratio'
            )
        }),
        ('Fechas', {
            'fields': ('creada', 'actualizada', 'ultima_evaluacion')
        }),
    )


@admin.register(PoblacionGenetica)
class PoblacionGeneticaAdmin(admin.ModelAdmin):
    list_display = [
        'nombre', 'generacion', 'tamano_poblacion', 'fitness_promedio',
        'fitness_mejor', 'fitness_peor', 'completada', 'creada'
    ]
    list_filter = ['completada', 'generacion', 'creada']
    search_fields = ['nombre']
    filter_horizontal = ['estrategias']
    readonly_fields = [
        'fitness_promedio', 'fitness_mejor', 'fitness_peor', 'creada', 'actualizada'
    ]


@admin.register(EvaluacionEstrategia)
class EvaluacionEstrategiaAdmin(admin.ModelAdmin):
    list_display = [
        'estrategia', 'fecha_inicio', 'fecha_fin', 'winrate',
        'beneficio_total', 'operaciones_totales', 'creada'
    ]
    list_filter = ['creada', 'fecha_inicio', 'fecha_fin']
    search_fields = ['estrategia__nombre']
    readonly_fields = [
        'operaciones_totales', 'operaciones_ganadas', 'operaciones_perdidas',
        'winrate', 'beneficio_total', 'max_drawdown', 'sharpe_ratio', 'creada'
    ]


@admin.register(EntrenamientoIA)
class EntrenamientoIAAdmin(admin.ModelAdmin):
    list_display = [
        'nombre', 'tipo', 'estado', 'generaciones', 'tamano_poblacion',
        'fitness_final', 'iniciada', 'finalizada', 'duracion_segundos'
    ]
    list_filter = ['estado', 'tipo', 'iniciada', 'finalizada']
    search_fields = ['nombre', 'error_mensaje']
    readonly_fields = [
        'estado', 'mejor_estrategia', 'fitness_final', 'progreso',
        'iniciada', 'finalizada', 'duracion_segundos', 'creada', 'actualizada'
    ]
    fieldsets = (
        ('Información básica', {
            'fields': ('nombre', 'tipo', 'estado')
        }),
        ('Parámetros', {
            'fields': (
                'generaciones', 'tamano_poblacion', 'datos_desde', 'datos_hasta',
                'activos_incluidos'
            )
        }),
        ('Resultados', {
            'fields': (
                'mejor_estrategia', 'fitness_final', 'progreso'
            )
        }),
        ('Control', {
            'fields': (
                'iniciada', 'finalizada', 'duracion_segundos', 'error_mensaje'
            )
        }),
    )

