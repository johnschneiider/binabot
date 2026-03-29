from django.contrib import admin
from .models import ConfiguracionTrading, ActivoTrading, EstadisticasTrading, OperacionTrading, TickTrading

@admin.register(ConfiguracionTrading)
class ConfiguracionTradingAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'ema_gap_min', 'adx_min', 'rsi_min', 'rsi_max', 'activa', 'updated_at']
    list_editable = ['activa']

@admin.register(ActivoTrading)
class ActivoTradingAdmin(admin.ModelAdmin):
    list_display = ['simbolo', 'nombre', 'pair_type', 'activo']
    list_editable = ['activo']

@admin.register(EstadisticasTrading)
class EstadisticasTradingAdmin(admin.ModelAdmin):
    list_display = ['simbolo', 'total_ops', 'wins', 'losses', 'win_rate', 'balance_ficticio']
    readonly_fields = ['win_rate']

@admin.register(OperacionTrading)
class OperacionTradingAdmin(admin.ModelAdmin):
    list_display = ['simbolo', 'direccion', 'es_win', 'profit', 'created_at']
    list_filter = ['simbolo', 'direccion', 'es_win']
    readonly_fields = ['created_at']

@admin.register(TickTrading)
class TickTradingAdmin(admin.ModelAdmin):
    list_display = ['simbolo', 'precio', 'timestamp']
    list_filter = ['simbolo']
