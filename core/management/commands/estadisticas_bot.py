"""
Comando para mostrar estadísticas del bot desde la base de datos.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Sum, Q
from decimal import Decimal
from datetime import timedelta
from core.models import ConfiguracionBot
from historial.models import Operacion


class Command(BaseCommand):
    help = "Muestra estadísticas del bot desde la base de datos"

    def add_arguments(self, parser):
        parser.add_argument(
            '--periodo',
            type=int,
            default=24,
            help='Horas hacia atrás para analizar (default: 24)',
        )

    def handle(self, *args, **options):
        periodo_horas = options['periodo']
        desde = timezone.now() - timedelta(hours=periodo_horas)
        
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("ESTADÍSTICAS DEL BOT"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        # 1. Estado actual del bot
        config = ConfiguracionBot.obtener()
        self.stdout.write("\n" + self.style.SUCCESS("1. ESTADO ACTUAL"))
        self.stdout.write(f"  Estado: {config.estado}")
        self.stdout.write(f"  Balance actual: ${config.balance_actual}")
        self.stdout.write(f"  Stop loss: ${config.stop_loss_actual}")
        self.stdout.write(f"  Ganancia acumulada: ${config.ganancia_acumulada}")
        self.stdout.write(f"  Pérdida acumulada: ${config.perdida_acumulada}")
        
        if config.estado == ConfiguracionBot.Estado.PAUSADO:
            if config.pausado_desde:
                self.stdout.write(f"  Pausado desde: {config.pausado_desde}")
            if config.pausa_finaliza:
                ahora = timezone.now()
                restante = config.pausa_finaliza - ahora
                if restante.total_seconds() > 0:
                    horas = int(restante.total_seconds() / 3600)
                    minutos = int((restante.total_seconds() % 3600) / 60)
                    self.stdout.write(f"  Se reactivará en: {horas}h {minutos}m")
        
        # 2. Operaciones totales
        self.stdout.write("\n" + self.style.SUCCESS("2. OPERACIONES TOTALES (Todas)"))
        operaciones_totales = Operacion.objetos.reales()
        total = operaciones_totales.count()
        ganadas = operaciones_totales.ganadas().count()
        perdidas = operaciones_totales.perdidas().count()
        
        if total > 0:
            winrate = (ganadas / total * 100)
            self.stdout.write(f"  Total operaciones: {total}")
            self.stdout.write(f"  Ganadas: {ganadas} ({winrate:.2f}%)")
            self.stdout.write(f"  Perdidas: {perdidas} ({100 - winrate:.2f}%)")
            
            # Beneficio total
            beneficio_total = sum(op.beneficio for op in operaciones_totales)
            self.stdout.write(f"  Beneficio total: ${beneficio_total}")
        else:
            self.stdout.write("  No hay operaciones registradas")
        
        # 3. Operaciones en el período
        self.stdout.write(f"\n" + self.style.SUCCESS(f"3. OPERACIONES ÚLTIMAS {periodo_horas} HORAS"))
        operaciones_periodo = operaciones_totales.filter(hora_inicio__gte=desde)
        total_periodo = operaciones_periodo.count()
        ganadas_periodo = operaciones_periodo.ganadas().count()
        perdidas_periodo = operaciones_periodo.perdidas().count()
        
        if total_periodo > 0:
            winrate_periodo = (ganadas_periodo / total_periodo * 100)
            self.stdout.write(f"  Total operaciones: {total_periodo}")
            self.stdout.write(f"  Ganadas: {ganadas_periodo} ({winrate_periodo:.2f}%)")
            self.stdout.write(f"  Perdidas: {perdidas_periodo} ({100 - winrate_periodo:.2f}%)")
            
            # Beneficio del período
            beneficio_periodo = sum(op.beneficio for op in operaciones_periodo)
            self.stdout.write(f"  Beneficio del período: ${beneficio_periodo}")
            
            # Promedio por operación
            promedio = beneficio_periodo / total_periodo
            self.stdout.write(f"  Promedio por operación: ${promedio:.2f}")
        else:
            self.stdout.write(f"  No hay operaciones en las últimas {periodo_horas} horas")
        
        # 4. Operaciones por dirección
        self.stdout.write("\n" + self.style.SUCCESS("4. OPERACIONES POR DIRECCIÓN (Total)"))
        call_ganadas = operaciones_totales.filter(
            direccion=Operacion.Direccion.CALL,
            resultado=Operacion.Resultado.GANADA
        ).count()
        call_perdidas = operaciones_totales.filter(
            direccion=Operacion.Direccion.CALL,
            resultado=Operacion.Resultado.PERDIDA
        ).count()
        put_ganadas = operaciones_totales.filter(
            direccion=Operacion.Direccion.PUT,
            resultado=Operacion.Resultado.GANADA
        ).count()
        put_perdidas = operaciones_totales.filter(
            direccion=Operacion.Direccion.PUT,
            resultado=Operacion.Resultado.PERDIDA
        ).count()
        
        call_total = call_ganadas + call_perdidas
        put_total = put_ganadas + put_perdidas
        
        if call_total > 0:
            call_winrate = (call_ganadas / call_total * 100)
            self.stdout.write(f"  CALL: {call_ganadas}G / {call_perdidas}P ({call_winrate:.2f}% winrate)")
        else:
            self.stdout.write("  CALL: Sin operaciones")
        
        if put_total > 0:
            put_winrate = (put_ganadas / put_total * 100)
            self.stdout.write(f"  PUT: {put_ganadas}G / {put_perdidas}P ({put_winrate:.2f}% winrate)")
        else:
            self.stdout.write("  PUT: Sin operaciones")
        
        # 5. Últimas 10 operaciones
        self.stdout.write("\n" + self.style.SUCCESS("5. ÚLTIMAS 10 OPERACIONES"))
        ultimas = operaciones_totales.order_by('-hora_inicio')[:10]
        
        if ultimas:
            for op in ultimas:
                resultado_emoji = "✅" if op.resultado == Operacion.Resultado.GANADA else "❌"
                beneficio_str = f"${op.beneficio:+.2f}"
                self.stdout.write(
                    f"  {resultado_emoji} {op.hora_inicio.strftime('%Y-%m-%d %H:%M')} | "
                    f"{op.activo} {op.direccion} | {beneficio_str}"
                )
        else:
            self.stdout.write("  No hay operaciones")
        
        # 6. Mejor y peor operación
        self.stdout.write("\n" + self.style.SUCCESS("6. MEJOR Y PEOR OPERACIÓN"))
        if operaciones_totales.exists():
            mejor = operaciones_totales.order_by('-beneficio').first()
            peor = operaciones_totales.order_by('beneficio').first()
            
            self.stdout.write(
                f"  Mejor: {mejor.activo} {mejor.direccion} | "
                f"${mejor.beneficio} | {mejor.hora_inicio.strftime('%Y-%m-%d %H:%M')}"
            )
            self.stdout.write(
                f"  Peor: {peor.activo} {peor.direccion} | "
                f"${peor.beneficio} | {peor.hora_inicio.strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            self.stdout.write("  No hay operaciones")
        
        # 7. Activos más operados
        self.stdout.write("\n" + self.style.SUCCESS("7. ACTIVOS MÁS OPERADOS (Top 5)"))
        
        activos_stats = operaciones_totales.values('activo').annotate(
            total=Count('id'),
            ganadas=Count('id', filter=Q(resultado=Operacion.Resultado.GANADA)),
            beneficio_total=Sum('beneficio')
        ).order_by('-total')[:5]
        
        if activos_stats:
            for stat in activos_stats:
                activo = stat['activo']
                total = stat['total']
                ganadas = stat['ganadas']
                winrate = (ganadas / total * 100) if total > 0 else 0
                beneficio = stat['beneficio_total'] or Decimal("0.00")
                self.stdout.write(
                    f"  {activo}: {total} ops | {ganadas}G ({winrate:.1f}%) | ${beneficio}"
                )
        else:
            self.stdout.write("  No hay datos")
        
        # 8. Resumen
        self.stdout.write("\n" + self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("RESUMEN"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        if total > 0:
            winrate_total = (ganadas / total * 100)
            beneficio_total = sum(op.beneficio for op in operaciones_totales)
            
            self.stdout.write(f"  Winrate total: {winrate_total:.2f}%")
            self.stdout.write(f"  Beneficio total: ${beneficio_total:.2f}")
            self.stdout.write(f"  Balance actual: ${config.balance_actual}")
            self.stdout.write(f"  Stop loss: ${config.stop_loss_actual}")
            
            # Margen de seguridad
            margen = ((config.balance_actual - config.stop_loss_actual) / config.balance_actual * 100) if config.balance_actual > 0 else 0
            self.stdout.write(f"  Margen de seguridad: {margen:.2f}%")
            
            # Análisis de rentabilidad
            if winrate_total >= 50 and beneficio_total > 0:
                self.stdout.write(self.style.SUCCESS("  ✅ Bot rentable"))
            elif winrate_total >= 50:
                self.stdout.write(self.style.WARNING("  ⚠️  Winrate bueno pero beneficio negativo (revisar montos)"))
            else:
                self.stdout.write(self.style.ERROR("  ❌ Winrate por debajo del 50% - Estrategia necesita ajustes"))
                
            # Comparar con período reciente
            if total_periodo > 0:
                winrate_periodo = (ganadas_periodo / total_periodo * 100)
                if winrate_periodo < winrate_total:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  Tendencia negativa: Winrate reciente ({winrate_periodo:.2f}%) < Winrate total ({winrate_total:.2f}%)"))
                elif winrate_periodo > winrate_total:
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Tendencia positiva: Winrate reciente ({winrate_periodo:.2f}%) > Winrate total ({winrate_total:.2f}%)"))
        else:
            self.stdout.write("  No hay suficientes datos para resumir")

