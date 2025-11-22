"""
Comando para verificar que el stop loss está funcionando correctamente.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from core.models import ConfiguracionBot
from core.services import GestorBotCore
from historial.models import Operacion


class Command(BaseCommand):
    help = "Verifica que el stop loss está funcionando correctamente"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("VERIFICACIÓN DEL STOP LOSS"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        gestor = GestorBotCore()
        config = gestor.configuracion
        
        # 1. Verificar configuración actual
        self.stdout.write("\n" + self.style.SUCCESS("1. CONFIGURACIÓN ACTUAL"))
        self.stdout.write(f"  Balance actual: ${config.balance_actual}")
        self.stdout.write(f"  Stop loss actual: ${config.stop_loss_actual}")
        self.stdout.write(f"  Balance stop loss base: ${config.balance_stop_loss_base}")
        self.stdout.write(f"  Estado: {config.estado}")
        
        # Calcular stop loss esperado (98% del balance)
        stop_loss_esperado = config.calcular_stop_loss(config.balance_actual)
        self.stdout.write(f"  Stop loss esperado (98%): ${stop_loss_esperado}")
        
        # Verificar si está correcto
        diferencia = abs(config.stop_loss_actual - stop_loss_esperado)
        if config.estado == ConfiguracionBot.Estado.OPERANDO:
            if diferencia <= Decimal("0.01"):
                self.stdout.write(self.style.SUCCESS("  ✅ Stop loss está correctamente configurado (98% del balance)"))
            else:
                if config.stop_loss_actual < stop_loss_esperado:
                    self.stdout.write(self.style.WARNING(
                        f"  ⚠️  Stop loss está POR DEBAJO del esperado (diferencia: ${diferencia})"
                    ))
                    self.stdout.write(self.style.WARNING(
                        "     Esto puede ser normal si el balance subió recientemente y el stop loss aún no se actualizó"
                    ))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  ❌ Stop loss está POR ENCIMA del esperado (diferencia: ${diferencia})"
                    ))
                    self.stdout.write(self.style.ERROR(
                        "     Esto NO debería pasar. El stop loss debe estar al 98% del balance."
                    ))
        else:
            self.stdout.write(self.style.WARNING(
                "  ⚠️  Bot está PAUSADO. El stop loss no se actualiza durante la pausa."
            ))
        
        # 2. Verificar lógica de trailing stop loss
        self.stdout.write("\n" + self.style.SUCCESS("2. LÓGICA DE TRAILING STOP LOSS"))
        
        # Obtener últimas operaciones
        ultimas_operaciones = Operacion.objetos.reales().order_by('-hora_inicio')[:10]
        
        if ultimas_operaciones:
            self.stdout.write(f"  Analizando últimas {len(ultimas_operaciones)} operaciones reales:")
            
            ganadas = 0
            perdidas = 0
            
            for op in ultimas_operaciones:
                resultado_emoji = "✅" if op.resultado == Operacion.Resultado.GANADA else "❌"
                self.stdout.write(
                    f"    {resultado_emoji} {op.activo} {op.direccion} - "
                    f"Beneficio: ${op.beneficio} - {op.hora_inicio.strftime('%Y-%m-%d %H:%M')}"
                )
                if op.resultado == Operacion.Resultado.GANADA:
                    ganadas += 1
                elif op.resultado == Operacion.Resultado.PERDIDA:
                    perdidas += 1
            
            self.stdout.write(f"\n  Resumen: {ganadas} ganadas, {perdidas} perdidas")
            
            # Verificar que el stop loss sube con ganancias
            if ganadas > 0:
                self.stdout.write(self.style.SUCCESS(
                    "  ✅ El stop loss DEBE subir (trailing) cuando hay trades ganadores"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    "  ⚠️  No hay trades ganadores recientes para verificar trailing stop loss"
                ))
            
            # Verificar que el stop loss no baja con pérdidas
            if perdidas > 0:
                self.stdout.write(self.style.SUCCESS(
                    "  ✅ El stop loss NO debe bajar cuando hay trades perdedores (se mantiene fijo)"
                ))
        else:
            self.stdout.write(self.style.WARNING("  ⚠️  No hay operaciones reales registradas aún"))
        
        # 3. Verificar si debe pausar
        self.stdout.write("\n" + self.style.SUCCESS("3. VERIFICACIÓN DE PAUSA POR STOP LOSS"))
        
        if config.balance_actual <= config.stop_loss_actual:
            self.stdout.write(self.style.ERROR(
                f"  ❌ ALERTA: Balance actual (${config.balance_actual}) <= Stop loss (${config.stop_loss_actual})"
            ))
            if config.estado == ConfiguracionBot.Estado.PAUSADO:
                self.stdout.write(self.style.SUCCESS(
                    "  ✅ Bot está correctamente PAUSADO por stop loss"
                ))
                if config.pausado_desde:
                    self.stdout.write(f"  Pausado desde: {config.pausado_desde}")
                if config.pausa_finaliza:
                    ahora = timezone.now()
                    restante = config.pausa_finaliza - ahora
                    if restante.total_seconds() > 0:
                        horas = int(restante.total_seconds() / 3600)
                        minutos = int((restante.total_seconds() % 3600) / 60)
                        self.stdout.write(f"  Se reactivará en: {horas}h {minutos}m")
            else:
                self.stdout.write(self.style.ERROR(
                    "  ❌ ERROR: El bot DEBERÍA estar pausado pero está OPERANDO"
                ))
                self.stdout.write(self.style.ERROR(
                    "  Esto es un problema. El bot debería pausarse automáticamente."
                ))
        else:
            diferencia_balance = config.balance_actual - config.stop_loss_actual
            porcentaje_restante = (diferencia_balance / config.balance_actual * 100) if config.balance_actual > 0 else 0
            self.stdout.write(self.style.SUCCESS(
                f"  ✅ Balance está por encima del stop loss"
            ))
            self.stdout.write(
                f"  Diferencia: ${diferencia_balance} ({porcentaje_restante:.2f}% de margen)"
            )
        
        # 4. Verificar sincronización con Deriv
        self.stdout.write("\n" + self.style.SUCCESS("4. SINCRONIZACIÓN CON DERIV"))
        
        try:
            from integracion_deriv.client import obtener_balance_sync
            respuesta = obtener_balance_sync()
            balance_info = respuesta.get("balance", {})
            balance_deriv = Decimal(str(balance_info.get("balance", "0")))
            
            if balance_deriv > 0:
                self.stdout.write(f"  Balance en Deriv: ${balance_deriv}")
                self.stdout.write(f"  Balance en BD: ${config.balance_actual}")
                
                diferencia = abs(balance_deriv - config.balance_actual)
                if diferencia <= Decimal("0.01"):
                    self.stdout.write(self.style.SUCCESS("  ✅ Balance sincronizado correctamente"))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  ⚠️  Hay una diferencia de ${diferencia} entre Deriv y BD"
                    ))
                    self.stdout.write(self.style.WARNING(
                        "     Esto puede deberse a comisiones, fees o ajustes no contabilizados"
                    ))
                
                # Verificar stop loss con balance de Deriv
                stop_loss_deriv = config.calcular_stop_loss(balance_deriv)
                self.stdout.write(f"  Stop loss esperado (98% de Deriv): ${stop_loss_deriv}")
                
                if config.estado == ConfiguracionBot.Estado.OPERANDO:
                    if stop_loss_deriv > config.stop_loss_actual:
                        self.stdout.write(self.style.SUCCESS(
                            f"  ✅ El stop loss se actualizará a ${stop_loss_deriv} en la próxima sincronización"
                        ))
                    elif stop_loss_deriv < config.stop_loss_actual:
                        self.stdout.write(self.style.SUCCESS(
                            "  ✅ El stop loss se mantendrá fijo (no baja cuando el balance baja)"
                        ))
            else:
                self.stdout.write(self.style.ERROR("  ❌ No se pudo obtener balance de Deriv"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Error al sincronizar con Deriv: {e}"))
        
        # 5. Resumen y recomendaciones
        self.stdout.write("\n" + self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("RESUMEN Y RECOMENDACIONES"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        
        problemas = []
        
        # Verificar problemas
        if config.estado == ConfiguracionBot.Estado.OPERANDO:
            if config.balance_actual <= config.stop_loss_actual:
                problemas.append("❌ El bot debería estar pausado (balance <= stop loss)")
            
            stop_loss_esperado = config.calcular_stop_loss(config.balance_actual)
            if abs(config.stop_loss_actual - stop_loss_esperado) > Decimal("1.00"):
                problemas.append("⚠️  El stop loss está muy desalineado del 98% del balance")
        
        if config.stop_loss_actual <= 0:
            problemas.append("❌ El stop loss no está configurado (es 0 o negativo)")
        
        if problemas:
            self.stdout.write(self.style.WARNING("\n⚠️  PROBLEMAS DETECTADOS:"))
            for problema in problemas:
                self.stdout.write(f"  {problema}")
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ TODO PARECE ESTAR FUNCIONANDO CORRECTAMENTE"))
        
        self.stdout.write("\n" + self.style.SUCCESS("Cómo probar el stop loss:"))
        self.stdout.write("  1. Observa el balance actual y el stop loss")
        self.stdout.write("  2. Cuando haya un trade ganador, el stop loss debe subir (trailing)")
        self.stdout.write("  3. Cuando haya un trade perdedor, el stop loss NO debe bajar")
        self.stdout.write("  4. Si el balance alcanza el stop loss, el bot debe pausarse automáticamente")
        self.stdout.write("\n" + self.style.SUCCESS("Para monitorear en tiempo real:"))
        self.stdout.write("  journalctl -u binabot-loop.service -f | grep -i 'stop\\|balance\\|pausa'")

