from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.conf import settings

from core.models import ActivoPermitido, ConfiguracionBot
from historial.models import Tick
from trading.services_profesional import MotorTradingProfesional
from trading.models import CooldownActivo


class Command(BaseCommand):
    help = "Diagnostica por qué el bot no está generando operaciones"

    def handle(self, *args, **options):
        self.stdout.write("=" * 80)
        self.stdout.write("DIAGNÓSTICO: ¿Por qué no se generan operaciones?")
        self.stdout.write("=" * 80)
        self.stdout.write("")

        motor = MotorTradingProfesional()
        config = ConfiguracionBot.objects.first()
        
        # 1. Verificar estado del bot
        self.stdout.write("1. ESTADO DEL BOT:")
        self.stdout.write(f"   Estado: {config.estado if config else 'NO CONFIGURADO'}")
        self.stdout.write(f"   en_operacion: {config.en_operacion if config else 'N/A'}")
        if config:
            if config.estado != ConfiguracionBot.Estado.OPERANDO:
                self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: Bot no está en estado OPERANDO"))
            elif config.en_operacion:
                self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: Bot ya tiene una operación en curso"))
            else:
                self.stdout.write(self.style.SUCCESS("   ✅ Estado correcto"))
        self.stdout.write("")

        # 2. Verificar stop loss
        self.stdout.write("2. STOP LOSS:")
        if config:
            self.stdout.write(f"   stop_loss_actual: {config.stop_loss_actual}")
            if config.stop_loss_actual <= 0:
                self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: Stop loss no está configurado correctamente"))
            else:
                self.stdout.write(self.style.SUCCESS("   ✅ Stop loss configurado"))
        self.stdout.write("")

        # 3. Verificar token de Deriv
        self.stdout.write("3. TOKEN DE DERIV:")
        if not settings.DERIV_API_TOKEN:
            self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: Token de Deriv no configurado"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✅ Token configurado"))
        self.stdout.write("")

        # 4. Verificar balance
        self.stdout.write("4. BALANCE:")
        if config:
            self.stdout.write(f"   balance_actual: {config.balance_actual}")
            if config.balance_actual <= 0:
                self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: Balance insuficiente"))
            else:
                self.stdout.write(self.style.SUCCESS("   ✅ Balance disponible"))
        self.stdout.write("")

        # 5. Verificar activos habilitados
        activos_habilitados = ActivoPermitido.objects.filter(habilitado=True)
        total_habilitados = activos_habilitados.count()
        self.stdout.write(f"5. ACTIVOS HABILITADOS: {total_habilitados}")
        self.stdout.write("")

        if total_habilitados == 0:
            self.stdout.write(self.style.ERROR("[ERROR] PROBLEMA: No hay activos habilitados"))
            return

        # 6. Verificar cooldowns
        self.stdout.write("6. COOLDOWNS:")
        cooldowns_activos = CooldownActivo.objects.filter(finaliza_en__gt=timezone.now())
        self.stdout.write(f"   Cooldowns activos: {cooldowns_activos.count()}")
        if cooldowns_activos.exists():
            for c in cooldowns_activos[:5]:
                self.stdout.write(f"   - {c.activo.nombre}: hasta {c.finaliza_en} ({c.motivo})")
        self.stdout.write("")

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
            self.stdout.write("7. EVALUANDO SEÑALES EMA:")
            self.stdout.write("")

            resultados = motor._evaluar_activos()
            
            if not resultados:
                self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: No se encontraron señales EMA válidas"))
                self.stdout.write("   Posibles causas:")
                self.stdout.write("   - Separación entre EMAs menor al umbral (0.01%)")
                self.stdout.write("   - Dirección = NONE (EMAs muy cercanas)")
                self.stdout.write("   - Activos en cooldown")
            else:
                self.stdout.write(f"   ✅ Se encontraron {len(resultados)} señales EMA")
                self.stdout.write("")
                self.stdout.write("   Top 5 señales:")
                for i, resultado in enumerate(resultados[:5], 1):
                    activo = resultado["activo"]
                    score = resultado["score"]
                    indicadores = resultado["indicadores"]
                    direccion = indicadores.direccion_sugerida
                    
                    estado = "✅ VÁLIDA" if score >= motor.umbral_separacion_pct and direccion != "NONE" else "⚠️ INSUFICIENTE"
                    self.stdout.write(
                        f"      {i}. {activo.nombre}: "
                        f"Separación={score:.4f}%, "
                        f"Dirección={direccion}, "
                        f"Estado={estado}"
                    )
                
                # 8. Simular ciclo completo
                self.stdout.write("")
                self.stdout.write("8. SIMULANDO CICLO COMPLETO:")
                self.stdout.write("")
                
                if resultados:
                    mejor_resultado = resultados[0]
                    mejor_activo = mejor_resultado["activo"]
                    mejor_indicadores = mejor_resultado["indicadores"]
                    mejor_score = mejor_resultado["score"]
                    
                    self.stdout.write(f"   Mejor activo: {mejor_activo.nombre}")
                    self.stdout.write(f"   Separación EMA: {mejor_score:.4f}% (umbral mínimo: {motor.umbral_separacion_pct}%)")
                    
                    if mejor_score < motor.umbral_separacion_pct:
                        self.stdout.write(self.style.ERROR(f"   ❌ PROBLEMA: Separación insuficiente"))
                    else:
                        self.stdout.write(self.style.SUCCESS("   ✅ Separación suficiente"))
                    
                    direccion = mejor_indicadores.direccion_sugerida
                    self.stdout.write(f"   Dirección sugerida: {direccion}")
                    
                    if direccion == "NONE":
                        self.stdout.write(self.style.ERROR("   ❌ PROBLEMA: Sin dirección clara (EMAs muy cercanas)"))
                    else:
                        self.stdout.write(self.style.SUCCESS("   ✅ Dirección válida"))
                        
                        # Verificar modo inverso
                        if config and config.modo_inverso:
                            direccion_final = "PUT" if direccion == "CALL" else "CALL"
                            self.stdout.write(f"   Modo inverso: ACTIVO → {direccion} → {direccion_final}")
                        
                        # Verificar cooldown del mejor activo
                        from trading.risk import verificar_cooldown
                        if not verificar_cooldown(mejor_activo.id):
                            self.stdout.write(self.style.ERROR(f"   ❌ PROBLEMA: {mejor_activo.nombre} está en cooldown"))
                        else:
                            self.stdout.write(self.style.SUCCESS(f"   ✅ {mejor_activo.nombre} no está en cooldown"))
                            
                            # Si llegamos aquí, debería operar
                            self.stdout.write("")
                            self.stdout.write(self.style.SUCCESS("   ✅ TODAS LAS CONDICIONES CUMPLIDAS"))
                            self.stdout.write(self.style.WARNING("   ⚠️  Si el bot no opera, puede ser un problema con la API de Deriv"))

        self.stdout.write("")
        self.stdout.write("=" * 80)

