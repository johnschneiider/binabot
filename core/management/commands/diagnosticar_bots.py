"""
Comando para diagnosticar por qué los bots no están operando.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import ConfiguracionBot, ActivoPermitido
from trading_inverso.models import ConfiguracionBotInverso, OperacionInversa
from historial.models import Operacion
from integracion_deriv.client import obtener_balance_sync
from core.services import GestorBotCore
from trading_inverso.services import GestorBotInverso
from trading.services_profesional import MotorTradingProfesional


class Command(BaseCommand):
    help = "Diagnostica por qué los bots no están operando"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n" + "="*80))
        self.stdout.write(self.style.SUCCESS("DIAGNÓSTICO DE BOTS"))
        self.stdout.write(self.style.SUCCESS("="*80 + "\n"))

        # 1. Verificar Balance de Deriv
        self.stdout.write(self.style.WARNING("1. VERIFICANDO BALANCE DE DERIV..."))
        try:
            respuesta = obtener_balance_sync()
            balance_info = respuesta.get('balance', {})
            balance_deriv = balance_info.get('balance', 0)
            self.stdout.write(f"   ✅ Balance en Deriv: ${balance_deriv:.2f}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ❌ Error obteniendo balance Deriv: {e}"))
            balance_deriv = 0

        # 2. Bot Principal
        self.stdout.write(self.style.WARNING("\n2. ESTADO DEL BOT PRINCIPAL..."))
        config_principal = ConfiguracionBot.obtener()
        self.stdout.write(f"   Estado: {config_principal.estado}")
        self.stdout.write(f"   Balance: ${config_principal.balance_actual:.2f}")
        self.stdout.write(f"   Stop Loss: ${config_principal.stop_loss_actual:.2f}")
        self.stdout.write(f"   En operación: {config_principal.en_operacion}")
        
        if config_principal.pausado_desde:
            self.stdout.write(f"   Pausado desde: {config_principal.pausado_desde}")
            if config_principal.pausa_finaliza:
                tiempo_restante = config_principal.pausa_finaliza - timezone.now()
                self.stdout.write(f"   Se reactivará en: {tiempo_restante}")
        
        puede_operar_principal = (
            config_principal.estado == ConfiguracionBot.Estado.OPERANDO and
            config_principal.balance_actual > config_principal.stop_loss_actual and
            not config_principal.en_operacion
        )
        
        if puede_operar_principal:
            self.stdout.write(self.style.SUCCESS("   ✅ Bot principal PUEDE operar"))
        else:
            self.stdout.write(self.style.ERROR("   ❌ Bot principal NO puede operar"))
            if config_principal.estado != ConfiguracionBot.Estado.OPERANDO:
                self.stdout.write(f"      Razón: Estado es '{config_principal.estado}' (debe ser 'operando')")
            if config_principal.balance_actual <= config_principal.stop_loss_actual:
                self.stdout.write(f"      Razón: Balance (${config_principal.balance_actual:.2f}) <= Stop Loss (${config_principal.stop_loss_actual:.2f})")
            if config_principal.en_operacion:
                self.stdout.write("      Razón: Ya hay una operación en curso")

        # 3. Bot Inverso
        self.stdout.write(self.style.WARNING("\n3. ESTADO DEL BOT INVERSO..."))
        config_inverso = ConfiguracionBotInverso.obtener()
        self.stdout.write(f"   Estado: {config_inverso.estado}")
        self.stdout.write(f"   Balance: ${config_inverso.balance_actual:.2f}")
        self.stdout.write(f"   Stop Loss: ${config_inverso.stop_loss_actual:.2f}")
        self.stdout.write(f"   En operación: {config_inverso.en_operacion}")
        
        if config_inverso.pausado_desde:
            self.stdout.write(f"   Pausado desde: {config_inverso.pausado_desde}")
            if config_inverso.pausa_finaliza:
                tiempo_restante = config_inverso.pausa_finaliza - timezone.now()
                self.stdout.write(f"   Se reactivará en: {tiempo_restante}")
        
        puede_operar_inverso = (
            config_inverso.estado == ConfiguracionBotInverso.Estado.OPERANDO and
            config_inverso.balance_actual > config_inverso.stop_loss_actual and
            not config_inverso.en_operacion
        )
        
        if puede_operar_inverso:
            self.stdout.write(self.style.SUCCESS("   ✅ Bot inverso PUEDE operar"))
        else:
            self.stdout.write(self.style.ERROR("   ❌ Bot inverso NO puede operar"))
            if config_inverso.estado != ConfiguracionBotInverso.Estado.OPERANDO:
                self.stdout.write(f"      Razón: Estado es '{config_inverso.estado}' (debe ser 'operando')")
            if config_inverso.balance_actual <= config_inverso.stop_loss_actual:
                self.stdout.write(f"      Razón: Balance (${config_inverso.balance_actual:.2f}) <= Stop Loss (${config_inverso.stop_loss_actual:.2f})")
            if config_inverso.en_operacion:
                self.stdout.write("      Razón: Ya hay una operación en curso")

        # 4. Activos Permitidos
        self.stdout.write(self.style.WARNING("\n4. ACTIVOS PERMITIDOS..."))
        activos = ActivoPermitido.objects.filter(activo=True)
        self.stdout.write(f"   Total activos activos: {activos.count()}")
        if activos.count() == 0:
            self.stdout.write(self.style.ERROR("   ❌ NO HAY ACTIVOS PERMITIDOS - Los bots no pueden operar"))
        else:
            self.stdout.write("   Activos:")
            for a in activos[:10]:
                self.stdout.write(f"      - {a.nombre}")
            if activos.count() > 10:
                self.stdout.write(f"      ... y {activos.count() - 10} más")

        # 5. Últimas Operaciones
        self.stdout.write(self.style.WARNING("\n5. ÚLTIMAS OPERACIONES..."))
        
        ultima_principal = Operacion.objetos.reales().order_by('-hora_inicio').first()
        if ultima_principal:
            tiempo_desde = timezone.now() - ultima_principal.hora_inicio
            horas = tiempo_desde.total_seconds() / 3600
            self.stdout.write(f"   Bot Principal: {ultima_principal.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
            self.stdout.write(f"      Hace: {horas:.2f} horas")
            self.stdout.write(f"      {ultima_principal.activo} {ultima_principal.direccion} - {ultima_principal.resultado}")
        else:
            self.stdout.write(self.style.ERROR("   Bot Principal: ❌ NO HAY OPERACIONES"))
        
        ultima_inversa = OperacionInversa.objects.filter(simulada=False).order_by('-hora_inicio').first()
        if ultima_inversa:
            tiempo_desde = timezone.now() - ultima_inversa.hora_inicio
            horas = tiempo_desde.total_seconds() / 3600
            self.stdout.write(f"   Bot Inverso: {ultima_inversa.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
            self.stdout.write(f"      Hace: {horas:.2f} horas")
            self.stdout.write(f"      {ultima_inversa.activo} {ultima_inversa.direccion} - {ultima_inversa.resultado}")
        else:
            self.stdout.write(self.style.ERROR("   Bot Inverso: ❌ NO HAY OPERACIONES"))

        # 6. Probar Ejecución Manual (solo si el bot principal puede operar)
        if puede_operar_principal and activos.count() > 0:
            self.stdout.write(self.style.WARNING("\n6. PROBANDO EJECUCIÓN MANUAL DEL BOT PRINCIPAL..."))
            try:
                gestor = GestorBotCore()
                motor = MotorTradingProfesional()
                operacion = motor.ejecutar_ciclo()
                if operacion:
                    self.stdout.write(self.style.SUCCESS(f"   ✅ Operación creada manualmente: {operacion.numero_contrato}"))
                else:
                    self.stdout.write(self.style.ERROR("   ❌ No se creó operación"))
                    if hasattr(motor, 'ultimo_mensaje_diagnostico') and motor.ultimo_mensaje_diagnostico:
                        self.stdout.write(f"      Razón: {motor.ultimo_mensaje_diagnostico}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Error al ejecutar manualmente: {e}"))

        # 7. Resumen y Recomendaciones
        self.stdout.write(self.style.WARNING("\n" + "="*80))
        self.stdout.write(self.style.WARNING("RESUMEN Y RECOMENDACIONES"))
        self.stdout.write(self.style.WARNING("="*80 + "\n"))

        problemas = []
        soluciones = []

        if config_principal.estado != ConfiguracionBot.Estado.OPERANDO:
            problemas.append("Bot principal está pausado")
            soluciones.append("Ejecutar: python manage.py shell -c \"from core.models import ConfiguracionBot; ConfiguracionBot.obtener().reanudar()\"")

        if config_inverso.estado != ConfiguracionBotInverso.Estado.OPERANDO:
            problemas.append("Bot inverso está pausado")
            soluciones.append("Ejecutar: python manage.py shell -c \"from trading_inverso.models import ConfiguracionBotInverso; ConfiguracionBotInverso.obtener().reanudar()\"")

        if activos.count() == 0:
            problemas.append("No hay activos permitidos")
            soluciones.append("Activar activos desde el admin o ejecutar: python manage.py shell -c \"from core.models import ActivoPermitido; [ActivoPermitido.objects.get_or_create(nombre=n)[0].__setattr__('activo', True) or ActivoPermitido.objects.get_or_create(nombre=n)[0].save() for n in ['R_10', 'R_25', 'R_50', 'R_100', 'JD100', 'RDBEAR']]\"")

        if config_principal.balance_actual <= config_principal.stop_loss_actual:
            problemas.append("Balance del bot principal está en o por debajo del stop loss")
            soluciones.append("Sincronizar balance: python manage.py shell -c \"from core.services import GestorBotCore; GestorBotCore().sincronizar_balance_desde_api()\"")

        if config_inverso.balance_actual <= config_inverso.stop_loss_actual:
            problemas.append("Balance del bot inverso está en o por debajo del stop loss")
            soluciones.append("Sincronizar balance: python manage.py shell -c \"from trading_inverso.services import GestorBotInverso; GestorBotInverso().sincronizar_balance_desde_api()\"")

        if problemas:
            self.stdout.write(self.style.ERROR("PROBLEMAS ENCONTRADOS:"))
            for i, problema in enumerate(problemas, 1):
                self.stdout.write(f"   {i}. {problema}")
            
            self.stdout.write(self.style.SUCCESS("\nSOLUCIONES:"))
            for i, solucion in enumerate(soluciones, 1):
                self.stdout.write(f"   {i}. {solucion}")
        else:
            self.stdout.write(self.style.SUCCESS("✅ No se encontraron problemas obvios."))
            self.stdout.write("   Verifica los logs de los servicios systemd:")
            self.stdout.write("   sudo journalctl -u binabot-loop.service --since '10 minutes ago' --no-pager | tail -50")

        self.stdout.write("\n")

