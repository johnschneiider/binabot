from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from historial.models import Operacion, Tick, AjusteBalance
from core.models import ConfiguracionBot, ActivoPermitido
from simulacion.models import ResultadoHorarioSimulacion
from trading.models import CooldownActivo, IndicadoresActivo, RendimientoActivo
from trading.database.cache_manager import TickCache


class Command(BaseCommand):
    help = "Muestra estadísticas completas de los datos en la base de datos"

    def handle(self, *args, **options):
        self.stdout.write("\n" + "="*80)
        self.stdout.write("ESTADÍSTICAS DE LA BASE DE DATOS")
        self.stdout.write("="*80)
        
        # OPERACIONES
        self.stdout.write("\n📊 OPERACIONES")
        self.stdout.write("-" * 80)
        total_operaciones = Operacion.objects.count()
        reales = Operacion.objetos.reales().count()
        simuladas = Operacion.objetos.simuladas().count()
        ganadas = Operacion.objetos.reales().ganadas().count()
        perdidas = Operacion.objetos.reales().perdidas().count()
        pendientes = Operacion.objects.filter(resultado=Operacion.Resultado.PENDIENTE).count()
        
        self.stdout.write(f"Total de operaciones: {total_operaciones}")
        self.stdout.write(f"  - Reales: {reales}")
        self.stdout.write(f"  - Simuladas: {simuladas}")
        if reales > 0:
            winrate = (ganadas / reales * 100) if reales > 0 else 0
            self.stdout.write(f"  - Ganadas: {ganadas}")
            self.stdout.write(f"  - Perdidas: {perdidas}")
            self.stdout.write(f"  - Pendientes: {pendientes}")
            self.stdout.write(f"  - Winrate: {winrate:.2f}%")
            
            # Beneficio total
            beneficio_total = Operacion.objetos.reales().aggregate(
                total=Sum('beneficio')
            )['total'] or 0
            self.stdout.write(f"  - Beneficio total: ${beneficio_total}")
        
        # TICKS
        self.stdout.write("\n📈 TICKS")
        self.stdout.write("-" * 80)
        total_ticks = Tick.objects.count()
        self.stdout.write(f"Total de ticks: {total_ticks:,}")
        
        if total_ticks > 0:
            # Ticks por activo (top 10)
            ticks_por_activo = Tick.objects.values('activo').annotate(
                total=Count('id')
            ).order_by('-total')[:10]
            
            self.stdout.write("\nTop 10 activos por cantidad de ticks:")
            for item in ticks_por_activo:
                self.stdout.write(f"  - {item['activo']}: {item['total']:,} ticks")
            
            # Ticks más recientes y más antiguos
            tick_mas_reciente = Tick.objects.order_by('-epoch').first()
            tick_mas_antiguo = Tick.objects.order_by('epoch').first()
            if tick_mas_reciente and tick_mas_antiguo:
                self.stdout.write(f"\nTick más reciente: {tick_mas_reciente.epoch} ({tick_mas_reciente.activo})")
                self.stdout.write(f"Tick más antiguo: {tick_mas_antiguo.epoch} ({tick_mas_antiguo.activo})")
        
        # CACHE DE TICKS
        self.stdout.write("\n💾 CACHE DE TICKS")
        self.stdout.write("-" * 80)
        try:
            total_cache = TickCache.objects.count()
            self.stdout.write(f"Total de entradas en cache: {total_cache:,}")
        except Exception:
            self.stdout.write("Cache de ticks no disponible")
        
        # ACTIVOS PERMITIDOS
        self.stdout.write("\n🎯 ACTIVOS PERMITIDOS")
        self.stdout.write("-" * 80)
        total_activos = ActivoPermitido.objects.count()
        habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
        deshabilitados = ActivoPermitido.objects.filter(habilitado=False).count()
        self.stdout.write(f"Total de activos: {total_activos}")
        self.stdout.write(f"  - Habilitados: {habilitados}")
        self.stdout.write(f"  - Deshabilitados: {deshabilitados}")
        
        # RESULTADOS DE SIMULACIÓN
        self.stdout.write("\n🔬 RESULTADOS DE SIMULACIÓN")
        self.stdout.write("-" * 80)
        total_simulaciones = ResultadoHorarioSimulacion.objects.count()
        self.stdout.write(f"Total de resultados de simulación: {total_simulaciones:,}")
        
        if total_simulaciones > 0:
            # Simulaciones por activo (top 10)
            sim_por_activo = ResultadoHorarioSimulacion.objects.values('activo').annotate(
                total=Count('id')
            ).order_by('-total')[:10]
            
            self.stdout.write("\nTop 10 activos por cantidad de simulaciones:")
            for item in sim_por_activo:
                self.stdout.write(f"  - {item['activo']}: {item['total']:,} simulaciones")
        
        # COOLDOWNS
        self.stdout.write("\n⏸️  COOLDOWNS ACTIVOS")
        self.stdout.write("-" * 80)
        total_cooldowns = CooldownActivo.objects.count()
        self.stdout.write(f"Total de cooldowns registrados: {total_cooldowns}")
        
        # INDICADORES
        self.stdout.write("\n📊 INDICADORES")
        self.stdout.write("-" * 80)
        total_indicadores = IndicadoresActivo.objects.count()
        self.stdout.write(f"Total de indicadores: {total_indicadores:,}")
        
        # RENDIMIENTOS
        self.stdout.write("\n📈 RENDIMIENTOS")
        self.stdout.write("-" * 80)
        total_rendimientos = RendimientoActivo.objects.count()
        self.stdout.write(f"Total de rendimientos: {total_rendimientos:,}")
        
        # AJUSTES DE BALANCE
        self.stdout.write("\n💰 AJUSTES DE BALANCE")
        self.stdout.write("-" * 80)
        total_ajustes = AjusteBalance.objects.count()
        self.stdout.write(f"Total de ajustes de balance: {total_ajustes}")
        
        if total_ajustes > 0:
            # Diferencia total acumulada
            diferencia_total = AjusteBalance.objects.aggregate(
                total=Sum('diferencia')
            )['total'] or 0
            self.stdout.write(f"  - Diferencia total acumulada: ${diferencia_total}")
        
        # CONFIGURACIÓN DEL BOT
        self.stdout.write("\n⚙️  CONFIGURACIÓN DEL BOT")
        self.stdout.write("-" * 80)
        config = ConfiguracionBot.objects.first()
        if config:
            self.stdout.write(f"Balance actual: ${config.balance_actual}")
            self.stdout.write(f"Balance stop loss base: ${config.balance_stop_loss_base}")
            self.stdout.write(f"Stop loss actual: ${config.stop_loss_actual}")
            self.stdout.write(f"Pérdida acumulada: ${config.perdida_acumulada}")
            self.stdout.write(f"Ganancia acumulada: ${config.ganancia_acumulada}")
            self.stdout.write(f"Estado: {config.estado}")
            self.stdout.write(f"En operación: {config.en_operacion}")
            if config.activo_seleccionado:
                self.stdout.write(f"Activo seleccionado: {config.activo_seleccionado}")
        
        # RESUMEN GENERAL
        self.stdout.write("\n" + "="*80)
        self.stdout.write("RESUMEN GENERAL")
        self.stdout.write("="*80)
        self.stdout.write(f"Total de registros en BD:")
        self.stdout.write(f"  - Operaciones: {total_operaciones:,}")
        self.stdout.write(f"  - Ticks: {total_ticks:,}")
        self.stdout.write(f"  - Simulaciones: {total_simulaciones:,}")
        self.stdout.write(f"  - Indicadores: {total_indicadores:,}")
        self.stdout.write(f"  - Rendimientos: {total_rendimientos:,}")
        self.stdout.write(f"  - Cooldowns: {total_cooldowns:,}")
        self.stdout.write(f"  - Ajustes: {total_ajustes:,}")
        
        total_general = (
            total_operaciones + total_ticks + total_simulaciones + 
            total_indicadores + total_rendimientos + total_cooldowns + total_ajustes
        )
        self.stdout.write(f"\nTotal aproximado de registros: {total_general:,}")
        self.stdout.write("\n")

