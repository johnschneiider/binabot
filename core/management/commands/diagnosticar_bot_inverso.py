"""
Comando para diagnosticar por qué el bot inverso no está operando.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from historial.models import Operacion as OperacionPrincipal
from trading_inverso.models import OperacionInversa, ConfiguracionBotInverso
from trading_inverso.services import MotorTradingInverso, GestorBotInverso


class Command(BaseCommand):
    help = "Diagnostica por qué el bot inverso no está operando"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n" + "="*80))
        self.stdout.write(self.style.SUCCESS("DIAGNÓSTICO DEL BOT INVERSO"))
        self.stdout.write(self.style.SUCCESS("="*80 + "\n"))

        gestor = GestorBotInverso()
        config = gestor.configuracion

        # 1. Estado del bot inverso
        self.stdout.write(self.style.WARNING("1. ESTADO DEL BOT INVERSO..."))
        self.stdout.write(f"   Estado: {config.estado}")
        self.stdout.write(f"   Balance: ${config.balance_actual:.2f}")
        self.stdout.write(f"   Stop Loss: ${config.stop_loss_actual:.2f}")
        self.stdout.write(f"   En operación: {config.en_operacion}")
        
        puede_operar = (
            config.estado == ConfiguracionBotInverso.Estado.OPERANDO and
            config.balance_actual > config.stop_loss_actual and
            not config.en_operacion
        )
        
        if puede_operar:
            self.stdout.write(self.style.SUCCESS("   ✅ Bot inverso PUEDE operar"))
        else:
            self.stdout.write(self.style.ERROR("   ❌ Bot inverso NO puede operar"))
            if config.estado != ConfiguracionBotInverso.Estado.OPERANDO:
                self.stdout.write(f"      Razón: Estado es '{config.estado}' (debe ser 'operando')")
            if config.balance_actual <= config.stop_loss_actual:
                self.stdout.write(f"      Razón: Balance (${config.balance_actual:.2f}) <= Stop Loss (${config.stop_loss_actual:.2f})")
            if config.en_operacion:
                self.stdout.write("      Razón: Ya hay una operación en curso")

        # 2. Últimas operaciones del bot principal
        self.stdout.write(self.style.WARNING("\n2. ÚLTIMAS OPERACIONES DEL BOT PRINCIPAL..."))
        ultimas_principales = OperacionPrincipal.objetos.reales().order_by('-hora_inicio')[:5]
        
        if ultimas_principales:
            self.stdout.write(f"   Total operaciones principales: {OperacionPrincipal.objetos.reales().count()}")
            self.stdout.write("   Últimas 5 operaciones:")
            for op in ultimas_principales:
                tiempo_desde = timezone.now() - op.hora_inicio
                horas = tiempo_desde.total_seconds() / 3600
                self.stdout.write(f"      [{op.id}] {op.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')} - "
                                f"{op.activo} {op.direccion} {op.resultado} "
                                f"(hace {horas:.2f}h)")
        else:
            self.stdout.write(self.style.ERROR("   ❌ NO HAY OPERACIONES DEL BOT PRINCIPAL"))

        # 3. Últimas operaciones del bot inverso
        self.stdout.write(self.style.WARNING("\n3. ÚLTIMAS OPERACIONES DEL BOT INVERSO..."))
        ultimas_inversas = OperacionInversa.objects.filter(es_simulada=False).order_by('-hora_inicio')[:5]
        
        if ultimas_inversas:
            self.stdout.write(f"   Total operaciones inversas: {OperacionInversa.objects.filter(es_simulada=False).count()}")
            self.stdout.write("   Últimas 5 operaciones:")
            for op in ultimas_inversas:
                tiempo_desde = timezone.now() - op.hora_inicio
                horas = tiempo_desde.total_seconds() / 3600
                self.stdout.write(f"      [{op.id}] {op.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')} - "
                                f"{op.activo} {op.direccion} {op.resultado} "
                                f"(hace {horas:.2f}h)")
        else:
            self.stdout.write(self.style.ERROR("   ❌ NO HAY OPERACIONES DEL BOT INVERSO"))

        # 4. Verificar si hay operaciones principales sin operación inversa correspondiente
        self.stdout.write(self.style.WARNING("\n4. OPERACIONES PRINCIPALES SIN OPERACIÓN INVERSA..."))
        
        # Obtener últimas 10 operaciones principales
        ops_principales = OperacionPrincipal.objetos.reales().order_by('-hora_inicio')[:10]
        ops_sin_inversa = []
        
        for op_principal in ops_principales:
            # Verificar si existe operación inversa para esta operación principal
            existe_inversa = OperacionInversa.objects.filter(
                operacion_principal_id=op_principal.numero_contrato,
                es_simulada=False
            ).exists()
            
            if not existe_inversa:
                tiempo_desde = timezone.now() - op_principal.hora_inicio
                horas = tiempo_desde.total_seconds() / 3600
                ops_sin_inversa.append((op_principal, horas))
        
        if ops_sin_inversa:
            self.stdout.write(f"   ⚠️  Se encontraron {len(ops_sin_inversa)} operaciones principales sin operación inversa:")
            for op, horas in ops_sin_inversa[:5]:
                self.stdout.write(f"      [{op.id}] {op.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')} - "
                                f"{op.activo} {op.direccion} {op.resultado} "
                                f"(hace {horas:.2f}h, ID contrato: {op.numero_contrato})")
        else:
            self.stdout.write(self.style.SUCCESS("   ✅ Todas las operaciones principales tienen operación inversa"))

        # 5. Probar ejecución manual
        if puede_operar and ops_sin_inversa:
            self.stdout.write(self.style.WARNING("\n5. PROBANDO EJECUCIÓN MANUAL..."))
            try:
                # Tomar la última operación principal sin inversa
                op_principal = ops_sin_inversa[0][0]
                self.stdout.write(f"   Intentando ejecutar operación inversa para: {op_principal.activo} {op_principal.direccion}")
                
                motor = MotorTradingInverso()
                operacion_inversa = motor.ejecutar_ciclo_inverso(op_principal)
                
                if operacion_inversa:
                    self.stdout.write(self.style.SUCCESS(f"   ✅ Operación inversa creada: {operacion_inversa.numero_contrato}"))
                else:
                    self.stdout.write(self.style.ERROR("   ❌ No se pudo crear operación inversa"))
                    self.stdout.write("      Verifica los logs del servicio para más detalles")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Error al ejecutar manualmente: {e}"))
                import traceback
                self.stdout.write(traceback.format_exc())

        # 6. Verificar servicio systemd
        self.stdout.write(self.style.WARNING("\n6. VERIFICACIÓN DEL SERVICIO..."))
        self.stdout.write("   Ejecuta estos comandos para verificar el servicio:")
        self.stdout.write("   sudo systemctl status binabot-inverso.service")
        self.stdout.write("   sudo journalctl -u binabot-inverso.service --since '10 minutes ago' --no-pager | tail -50")

        # 7. Resumen
        self.stdout.write(self.style.WARNING("\n" + "="*80))
        self.stdout.write(self.style.WARNING("RESUMEN"))
        self.stdout.write(self.style.WARNING("="*80 + "\n"))

        problemas = []
        soluciones = []

        if not puede_operar:
            problemas.append("Bot inverso no puede operar (ver razones arriba)")
            if config.estado != ConfiguracionBotInverso.Estado.OPERANDO:
                soluciones.append("Reanudar bot: python manage.py shell -c \"from trading_inverso.models import ConfiguracionBotInverso; ConfiguracionBotInverso.obtener().reanudar()\"")

        if ops_sin_inversa:
            problemas.append(f"Hay {len(ops_sin_inversa)} operaciones principales sin operación inversa")
            soluciones.append("Verificar que el servicio binabot-inverso.service esté corriendo")
            soluciones.append("Ver logs: sudo journalctl -u binabot-inverso.service -f")

        if not OperacionPrincipal.objetos.reales().exists():
            problemas.append("No hay operaciones del bot principal")
            soluciones.append("El bot inverso depende del bot principal. Primero debe operar el bot principal")

        if problemas:
            self.stdout.write(self.style.ERROR("PROBLEMAS ENCONTRADOS:"))
            for i, problema in enumerate(problemas, 1):
                self.stdout.write(f"   {i}. {problema}")
            
            self.stdout.write(self.style.SUCCESS("\nSOLUCIONES:"))
            for i, solucion in enumerate(soluciones, 1):
                self.stdout.write(f"   {i}. {solucion}")
        else:
            self.stdout.write(self.style.SUCCESS("✅ No se encontraron problemas obvios."))
            self.stdout.write("   El bot inverso debería estar operando. Verifica los logs del servicio.")

        self.stdout.write("\n")

