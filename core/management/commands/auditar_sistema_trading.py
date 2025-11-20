"""
Comando de auditoría completa del sistema de trading.
Verifica el flujo completo: entradas, análisis y duración de trades.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from core.models import ConfiguracionBot, ActivoPermitido
from historial.models import Operacion
from trading.models import CooldownActivo
from trading.services import MotorTrading
from trading.services_profesional import MotorTradingProfesional


class Command(BaseCommand):
    help = "Auditoría completa del sistema de trading"

    def add_arguments(self, parser):
        parser.add_argument(
            "--profesional",
            action="store_true",
            help="Verificar motor profesional",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("AUDITORÍA COMPLETA DEL SISTEMA DE TRADING"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        # 1. Verificar configuración del bot
        self.stdout.write(self.style.SUCCESS("1. CONFIGURACIÓN DEL BOT"))
        self.stdout.write("-" * 80)
        config = ConfiguracionBot.obtener()
        self.stdout.write(f"  Estado: {config.estado}")
        self.stdout.write(f"  En operación: {config.en_operacion}")
        self.stdout.write(f"  Balance actual: ${config.balance_actual}")
        self.stdout.write(f"  Stop loss: ${config.stop_loss_actual}")
        self.stdout.write(f"  Modo inverso: {'✅ ACTIVO' if config.modo_inverso else '❌ INACTIVO'}")
        self.stdout.write("")

        # 2. Verificar activos
        self.stdout.write(self.style.SUCCESS("2. ACTIVOS DISPONIBLES"))
        self.stdout.write("-" * 80)
        activos_habilitados = ActivoPermitido.objects.filter(habilitado=True)
        self.stdout.write(f"  Total activos habilitados: {activos_habilitados.count()}")
        
        cooldowns = CooldownActivo.objects.filter(finaliza_en__gt=timezone.now())
        self.stdout.write(f"  Cooldowns activos: {cooldowns.count()}")
        if cooldowns.exists():
            self.stdout.write("  Activos en cooldown:")
            for cd in cooldowns[:5]:
                self.stdout.write(f"    - {cd.activo.nombre}: {cd.motivo} (hasta {cd.finaliza_en})")
        self.stdout.write("")

        # 3. Verificar última operación
        self.stdout.write(self.style.SUCCESS("3. ÚLTIMA OPERACIÓN"))
        self.stdout.write("-" * 80)
        ultima_op = Operacion.objetos.reales().order_by('-hora_inicio').first()
        if ultima_op:
            if ultima_op.hora_inicio and ultima_op.hora_fin:
                duracion = ultima_op.hora_fin - ultima_op.hora_inicio
                segundos = duracion.total_seconds()
                self.stdout.write(f"  Activo: {ultima_op.activo}")
                self.stdout.write(f"  Dirección: {ultima_op.direccion}")
                self.stdout.write(f"  Duración: {segundos:.1f} segundos")
                self.stdout.write(f"  Creada: {ultima_op.hora_inicio}")
                self.stdout.write(f"  Cerrada: {ultima_op.hora_fin}")
                if segundos >= 50 and segundos <= 70:
                    self.stdout.write(self.style.SUCCESS("  ✅ Duración correcta (~60s)"))
                else:
                    self.stdout.write(self.style.WARNING(f"  ⚠️  Duración incorrecta (esperado ~60s, obtenido {segundos:.1f}s)"))
            else:
                self.stdout.write(f"  Operación pendiente: {ultima_op.activo} {ultima_op.direccion}")
        else:
            self.stdout.write("  No hay operaciones registradas")
        self.stdout.write("")

        # 4. Verificar código de duración
        self.stdout.write(self.style.SUCCESS("4. VERIFICACIÓN DE CÓDIGO"))
        self.stdout.write("-" * 80)
        usar_profesional = options.get("profesional", False)
        
        if usar_profesional:
            motor = MotorTradingProfesional()
            self.stdout.write("  Motor: PROFESIONAL")
            # Verificar código fuente
            import inspect
            source = inspect.getsource(motor.ejecutar_ciclo)
            if 'duration=60' in source and 'duration_unit="s"' in source:
                self.stdout.write(self.style.SUCCESS("  ✅ Código correcto: duration=60, duration_unit='s'"))
            else:
                self.stdout.write(self.style.ERROR("  ❌ Código incorrecto: no se encontró duration=60"))
        else:
            motor = MotorTrading()
            self.stdout.write("  Motor: SIMPLE")
            senal = motor.generar_senal("frxEURUSD")  # Test con un activo
            if senal:
                if senal.get("duracion") == 60 and senal.get("unidad_duracion") == "s":
                    self.stdout.write(self.style.SUCCESS("  ✅ Señal correcta: duracion=60, unidad_duracion='s'"))
                else:
                    self.stdout.write(self.style.ERROR(f"  ❌ Señal incorrecta: duracion={senal.get('duracion')}, unidad={senal.get('unidad_duracion')}"))
            else:
                self.stdout.write(self.style.WARNING("  ⚠️  No se pudo generar señal de prueba"))
        self.stdout.write("")

        # 5. Verificar API de Deriv
        self.stdout.write(self.style.SUCCESS("5. CONFIGURACIÓN API DERIV"))
        self.stdout.write("-" * 80)
        if settings.DERIV_API_TOKEN:
            self.stdout.write(self.style.SUCCESS("  ✅ Token configurado"))
        else:
            self.stdout.write(self.style.ERROR("  ❌ Token NO configurado"))
        
        if settings.DERIV_APP_ID:
            self.stdout.write(self.style.SUCCESS("  ✅ APP ID configurado"))
        else:
            self.stdout.write(self.style.ERROR("  ❌ APP ID NO configurado"))
        self.stdout.write("")

        # 6. Verificar condiciones para operar
        self.stdout.write(self.style.SUCCESS("6. CONDICIONES PARA OPERAR"))
        self.stdout.write("-" * 80)
        
        # Verificar estado
        if config.estado != config.Estado.OPERANDO:
            self.stdout.write(self.style.WARNING(f"  ⚠️  Bot no está OPERANDO (estado: {config.estado})"))
        else:
            self.stdout.write(self.style.SUCCESS("  ✅ Bot está OPERANDO"))
        
        # Verificar en_operacion
        if config.en_operacion:
            self.stdout.write(self.style.WARNING("  ⚠️  Ya hay una operación en curso"))
        else:
            self.stdout.write(self.style.SUCCESS("  ✅ No hay operación en curso"))
        
        # Verificar stop loss
        if config.stop_loss_actual <= 0:
            self.stdout.write(self.style.ERROR("  ❌ Stop loss no configurado"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  ✅ Stop loss configurado: ${config.stop_loss_actual}"))
        
        # Verificar activos disponibles
        activos_disponibles = activos_habilitados.exclude(
            id__in=cooldowns.values_list('activo_id', flat=True)
        )
        if activos_disponibles.exists():
            self.stdout.write(self.style.SUCCESS(f"  ✅ {activos_disponibles.count()} activos disponibles para operar"))
        else:
            self.stdout.write(self.style.WARNING("  ⚠️  No hay activos disponibles (todos en cooldown o deshabilitados)"))
        self.stdout.write("")

        # 7. Intentar ejecutar ciclo (solo diagnóstico, no crear operación)
        self.stdout.write(self.style.SUCCESS("7. DIAGNÓSTICO DE EJECUCIÓN"))
        self.stdout.write("-" * 80)
        if config.estado == config.Estado.OPERANDO and not config.en_operacion:
            try:
                # Solo verificar si puede evaluar activos, no ejecutar
                if usar_profesional:
                    resultados = motor._evaluar_activos()
                    if resultados:
                        mejor = resultados[0]
                        self.stdout.write(self.style.SUCCESS(f"  ✅ Se encontraron {len(resultados)} activos evaluados"))
                        self.stdout.write(f"     Mejor activo: {mejor['activo'].nombre} (score: {mejor['score']})")
                        if mejor['score'] < motor.umbral_score_minimo:
                            self.stdout.write(self.style.WARNING(f"     ⚠️  Score ({mejor['score']}) < umbral mínimo ({motor.umbral_score_minimo})"))
                        else:
                            self.stdout.write(self.style.SUCCESS(f"     ✅ Score ({mejor['score']}) >= umbral mínimo ({motor.umbral_score_minimo})"))
                    else:
                        self.stdout.write(self.style.WARNING("  ⚠️  No se encontraron activos evaluados"))
                else:
                    # Motor simple
                    activos = list(activos_disponibles[:5])
                    if activos:
                        self.stdout.write(f"  ✅ {len(activos)} activos disponibles para probar señales")
                    else:
                        self.stdout.write(self.style.WARNING("  ⚠️  No hay activos disponibles"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error al evaluar: {e}"))
        else:
            self.stdout.write(self.style.WARNING("  ⚠️  No se puede ejecutar diagnóstico (bot no está operando o hay operación en curso)"))
        self.stdout.write("")

        # 8. Resumen y recomendaciones
        self.stdout.write(self.style.SUCCESS("8. RESUMEN Y RECOMENDACIONES"))
        self.stdout.write("-" * 80)
        
        problemas = []
        if config.estado != config.Estado.OPERANDO:
            problemas.append("Bot no está en estado OPERANDO")
        if config.en_operacion:
            problemas.append("Hay una operación en curso")
        if not settings.DERIV_API_TOKEN:
            problemas.append("Token de Deriv no configurado")
        if config.stop_loss_actual <= 0:
            problemas.append("Stop loss no configurado")
        if not activos_disponibles.exists():
            problemas.append("No hay activos disponibles")
        
        if problemas:
            self.stdout.write(self.style.WARNING("  Problemas detectados:"))
            for problema in problemas:
                self.stdout.write(f"    - {problema}")
        else:
            self.stdout.write(self.style.SUCCESS("  ✅ No se detectaron problemas obvios"))
            self.stdout.write("     El bot debería poder generar operaciones")
        
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("AUDITORÍA COMPLETADA"))
        self.stdout.write(self.style.SUCCESS("=" * 80))

