"""
Comando para investigar a fondo por qué el bot se pausó.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.models import ConfiguracionBot
from historial.models import Operacion


class Command(BaseCommand):
    help = "Investiga a fondo por qué el bot se pausó"

    def handle(self, *args, **options):
        config = ConfiguracionBot.obtener()
        
        self.stdout.write(self.style.SUCCESS("\n" + "="*80))
        self.stdout.write(self.style.SUCCESS("INVESTIGACIÓN COMPLETA DE PAUSA"))
        self.stdout.write(self.style.SUCCESS("="*80 + "\n"))

        # 1. Estado actual
        self.stdout.write(self.style.WARNING("1. ESTADO ACTUAL:"))
        self.stdout.write(f"   Estado: {config.estado}")
        self.stdout.write(f"   Balance actual: ${config.balance_actual:.2f}")
        self.stdout.write(f"   Stop loss actual: ${config.stop_loss_actual:.2f}")
        self.stdout.write(f"   Balance stop loss base: ${config.balance_stop_loss_base:.2f}")
        self.stdout.write(f"   Pausado desde: {config.pausado_desde}")
        self.stdout.write(f"   Pausa finaliza: {config.pausa_finaliza}")
        
        if config.pausado_desde:
            tiempo_restante = config.pausa_finaliza - timezone.now() if config.pausa_finaliza else None
            if tiempo_restante:
                horas = int(tiempo_restante.total_seconds() / 3600)
                minutos = int((tiempo_restante.total_seconds() % 3600) / 60)
                self.stdout.write(f"   Tiempo restante: {horas}h {minutos}m")

        # 2. Verificar si el balance está por encima del stop loss
        if config.estado == 'pausado':
            if config.balance_actual > config.stop_loss_actual:
                self.stdout.write(self.style.ERROR("\n⚠️  PROBLEMA DETECTADO:"))
                self.stdout.write(f"   El bot está pausado pero el balance (${config.balance_actual:.2f}) está POR ENCIMA del stop loss (${config.stop_loss_actual:.2f})")
                self.stdout.write("   Esto NO debería pasar. El bot se pausó incorrectamente.")

        # 3. Reconstruir el historial de balance
        if config.pausado_desde:
            self.stdout.write(self.style.WARNING("\n2. RECONSTRUCCIÓN DEL HISTORIAL:"))
            
            # Obtener todas las operaciones desde 3 horas antes de la pausa
            desde = config.pausado_desde - timedelta(hours=3)
            hasta = config.pausado_desde + timedelta(minutes=10)
            
            ops = Operacion.objetos.reales().filter(
                hora_inicio__gte=desde,
                hora_inicio__lte=hasta
            ).order_by('hora_inicio')
            
            # Empezar desde el balance actual y retroceder
            balance_actual = config.balance_actual
            balance_historial = []
            
            # Retroceder operación por operación
            for op in reversed(ops):
                if op.hora_inicio < config.pausado_desde:
                    if op.resultado == 'win':
                        balance_antes = balance_actual - op.beneficio
                    else:
                        balance_antes = balance_actual + abs(op.beneficio)
                    
                    balance_historial.append({
                        'hora': op.hora_inicio,
                        'operacion': op,
                        'balance_despues': balance_actual,
                        'balance_antes': balance_antes,
                    })
                    balance_actual = balance_antes
            
            # Mostrar historial
            self.stdout.write(f"\n   Operaciones antes de la pausa (reconstrucción hacia atrás):")
            for item in balance_historial[:10]:
                op = item['operacion']
                tiempo_antes = (config.pausado_desde - op.hora_inicio).total_seconds() / 60
                stop_loss_en_ese_momento = config.calcular_stop_loss(item['balance_antes'])
                
                self.stdout.write(f"   {op.hora_inicio.strftime('%H:%M:%S')} | {op.resultado.upper()} | ${op.beneficio:.2f}")
                self.stdout.write(f"      Balance antes: ${item['balance_antes']:.2f} | Después: ${item['balance_despues']:.2f}")
                self.stdout.write(f"      Stop loss en ese momento: ${stop_loss_en_ese_momento:.2f}")
                
                if item['balance_antes'] <= stop_loss_en_ese_momento:
                    self.stdout.write(self.style.ERROR(f"      ⚠️  Balance ({item['balance_antes']:.2f}) <= Stop Loss ({stop_loss_en_ese_momento:.2f}) - ESTO CAUSÓ LA PAUSA"))
                else:
                    self.stdout.write(f"      ✅ Balance > Stop Loss")
                self.stdout.write(f"      {tiempo_antes:.1f} minutos antes de pausa\n")

        # 4. Verificar última operación antes de pausa
        if config.pausado_desde:
            self.stdout.write(self.style.WARNING("\n3. ÚLTIMA OPERACIÓN ANTES DE PAUSA:"))
            ultima_op = Operacion.objetos.reales().filter(
                hora_inicio__lt=config.pausado_desde
            ).order_by('-hora_inicio').first()
            
            if ultima_op:
                tiempo_antes = (config.pausado_desde - ultima_op.hora_inicio).total_seconds() / 60
                self.stdout.write(f"   {ultima_op.hora_inicio.strftime('%Y-%m-%d %H:%M:%S')} | {ultima_op.activo} {ultima_op.direccion} | {ultima_op.resultado} | ${ultima_op.beneficio:.2f}")
                self.stdout.write(f"   {tiempo_antes:.1f} minutos antes de la pausa")
                
                if ultima_op.resultado == 'win':
                    self.stdout.write(self.style.ERROR("   ⚠️  ÚLTIMA OPERACIÓN FUE GANADA - Esto NO debería causar pausa"))
                else:
                    # Calcular balance antes de esta operación
                    balance_antes_op = config.balance_actual - ultima_op.beneficio if ultima_op.resultado == 'win' else config.balance_actual + abs(ultima_op.beneficio)
                    stop_loss_antes = config.calcular_stop_loss(balance_antes_op)
                    self.stdout.write(f"   Balance antes de esta operación: ${balance_antes_op:.2f}")
                    self.stdout.write(f"   Stop loss en ese momento: ${stop_loss_antes:.2f}")
                    if balance_antes_op <= stop_loss_antes:
                        self.stdout.write(self.style.ERROR(f"   ⚠️  Balance ({balance_antes_op:.2f}) <= Stop Loss ({stop_loss_antes:.2f}) - ESTO CAUSÓ LA PAUSA"))

        # 5. Verificar sincronización de balance
        self.stdout.write(self.style.WARNING("\n4. VERIFICAR SINCRONIZACIÓN DE BALANCE:"))
        try:
            from integracion_deriv.client import obtener_balance_sync
            respuesta = obtener_balance_sync()
            balance_info = respuesta.get('balance', {})
            balance_deriv = Decimal(str(balance_info.get('balance', 0)))
            
            self.stdout.write(f"   Balance en Deriv: ${balance_deriv:.2f}")
            self.stdout.write(f"   Balance en BD: ${config.balance_actual:.2f}")
            diferencia = abs(float(balance_deriv - config.balance_actual))
            if diferencia > 0.10:
                self.stdout.write(self.style.ERROR(f"   ⚠️  DIFERENCIA DETECTADA: ${diferencia:.2f}"))
                self.stdout.write("   El balance en BD no coincide con Deriv. Esto puede causar pausas incorrectas.")
            else:
                self.stdout.write(self.style.SUCCESS("   ✅ Los balances coinciden"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   Error obteniendo balance de Deriv: {e}"))

        # 6. Recomendaciones
        self.stdout.write(self.style.WARNING("\n" + "="*80))
        self.stdout.write(self.style.WARNING("RECOMENDACIONES"))
        self.stdout.write(self.style.WARNING("="*80 + "\n"))

        if config.estado == 'pausado' and config.balance_actual > config.stop_loss_actual:
            self.stdout.write("1. El bot está pausado incorrectamente.")
            self.stdout.write("2. Reanudar el bot manualmente:")
            self.stdout.write("   python manage.py shell -c \"from core.models import ConfiguracionBot; ConfiguracionBot.obtener().reanudar()\"")
            self.stdout.write("3. Verificar logs del sistema para encontrar la causa exacta:")
            if config.pausado_desde:
                desde_str = config.pausado_desde.strftime('%Y-%m-%d %H:%M:%S')
                hasta_str = (config.pausado_desde + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
                self.stdout.write(f"   sudo journalctl -u binabot-loop.service --since \"{desde_str}\" --until \"{hasta_str}\" --no-pager")

        self.stdout.write("\n")

