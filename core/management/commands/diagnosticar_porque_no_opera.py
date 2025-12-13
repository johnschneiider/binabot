from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.models import ActivoPermitido
from historial.models import Tick
from trading.services_profesional import MotorTradingProfesional


class Command(BaseCommand):
    help = "Diagnostica por qué el bot no está generando operaciones"

    def handle(self, *args, **options):
        self.stdout.write("=" * 80)
        self.stdout.write("DIAGNÓSTICO: ¿Por qué no se generan operaciones?")
        self.stdout.write("=" * 80)
        self.stdout.write("")

        motor = MotorTradingProfesional()
        
        # Verificar activos habilitados
        activos_habilitados = ActivoPermitido.objects.filter(habilitado=True)
        total_habilitados = activos_habilitados.count()
        self.stdout.write(f"Activos habilitados: {total_habilitados}")
        self.stdout.write("")

        if total_habilitados == 0:
            self.stdout.write(self.style.ERROR("[ERROR] PROBLEMA: No hay activos habilitados"))
            return

        # Verificar ticks recientes por activo
        desde = timezone.now() - timedelta(seconds=motor.periodo_analisis_segundos)
        self.stdout.write(f"Verificando ticks de los últimos {motor.periodo_analisis_segundos} segundos...")
        self.stdout.write("")

        activos_sin_ticks = []
        activos_con_pocos_ticks = []
        activos_con_suficientes_ticks = []

        for activo in activos_habilitados[:10]:  # Revisar top 10
            ticks_recientes = Tick.objects.filter(
                activo=activo.nombre,
                epoch__gte=desde
            ).count()

            if ticks_recientes == 0:
                activos_sin_ticks.append(activo.nombre)
            elif ticks_recientes < motor.ema_lenta_periodo:
                activos_con_pocos_ticks.append((activo.nombre, ticks_recientes))
            else:
                activos_con_suficientes_ticks.append((activo.nombre, ticks_recientes))

        if activos_sin_ticks:
            self.stdout.write(self.style.WARNING(f"[SIN TICKS] Activos SIN ticks recientes ({len(activos_sin_ticks)}):"))
            for nombre in activos_sin_ticks[:5]:
                self.stdout.write(f"   - {nombre}")
            self.stdout.write("")

        if activos_con_pocos_ticks:
            self.stdout.write(self.style.WARNING(f"[POCOS TICKS] Activos con POCOS ticks (necesitan {motor.ema_lenta_periodo}, tienen menos):"))
            for nombre, count in activos_con_pocos_ticks[:5]:
                self.stdout.write(f"   - {nombre}: {count} ticks (necesita {motor.ema_lenta_periodo})")
            self.stdout.write("")

        if activos_con_suficientes_ticks:
            self.stdout.write(self.style.SUCCESS(f"✅ Activos con suficientes ticks:"))
            for nombre, count in activos_con_suficientes_ticks[:5]:
                self.stdout.write(f"   - {nombre}: {count} ticks")
            self.stdout.write("")

        # Evaluar activos con suficientes ticks
        if activos_con_suficientes_ticks:
            self.stdout.write("Evaluando señales EMA en activos con suficientes ticks...")
            self.stdout.write("")

            resultados = motor._evaluar_activos()
            
            if not resultados:
                self.stdout.write(self.style.ERROR("[ERROR] PROBLEMA: No se encontraron señales EMA válidas"))
                self.stdout.write("   Posibles causas:")
                self.stdout.write("   - Separación entre EMAs menor al umbral (0.01%)")
                self.stdout.write("   - Dirección = NONE (EMAs muy cercanas)")
                self.stdout.write("   - Activos en cooldown")
            else:
                self.stdout.write(f"✅ Se encontraron {len(resultados)} señales EMA")
                self.stdout.write("")
                self.stdout.write("Top 5 señales:")
                for i, resultado in enumerate(resultados[:5], 1):
                    activo = resultado["activo"]
                    score = resultado["score"]
                    indicadores = resultado["indicadores"]
                    direccion = indicadores.direccion_sugerida
                    
                    estado = "[OK] VÁLIDA" if score >= motor.umbral_separacion_pct and direccion != "NONE" else "[INSUFICIENTE]"
                    self.stdout.write(
                        f"   {i}. {activo.nombre}: "
                        f"Separación={score:.4f}%, "
                        f"Dirección={direccion}, "
                        f"Estado={estado}"
                    )

        self.stdout.write("")
        self.stdout.write("=" * 80)

