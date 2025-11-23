"""
Comando para buscar el momento exacto en que el bot se pausó en los logs.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import ConfiguracionBot
from historial.models import Operacion


class Command(BaseCommand):
    help = "Busca el momento exacto en que el bot se pausó"

    def handle(self, *args, **options):
        config = ConfiguracionBot.obtener()
        
        if not config.pausado_desde:
            self.stdout.write(self.style.SUCCESS("El bot NO está pausado actualmente."))
            return
        
        self.stdout.write(self.style.SUCCESS("\n" + "="*80))
        self.stdout.write(self.style.SUCCESS("BUSCAR MOMENTO EXACTO DE PAUSA"))
        self.stdout.write(self.style.SUCCESS("="*80 + "\n"))
        
        pausa_desde = config.pausado_desde
        
        self.stdout.write(f"Pausado desde: {pausa_desde}")
        self.stdout.write(f"Balance actual: ${config.balance_actual:.2f}")
        self.stdout.write(f"Stop loss actual: ${config.stop_loss_actual:.2f}\n")
        
        # Buscar operaciones en una ventana de tiempo alrededor de la pausa
        ventana_antes = timedelta(minutes=10)
        ventana_despues = timedelta(minutes=5)
        
        desde = pausa_desde - ventana_antes
        hasta = pausa_desde + ventana_despues
        
        self.stdout.write(self.style.WARNING(f"Buscando operaciones entre {desde.strftime('%Y-%m-%d %H:%M:%S')} y {hasta.strftime('%Y-%m-%d %H:%M:%S')}"))
        
        ops = Operacion.objetos.reales().filter(
            hora_inicio__gte=desde,
            hora_inicio__lte=hasta
        ).order_by('hora_inicio')
        
        # Reconstruir balance paso a paso
        balance_inicial = config.balance_actual
        
        # Retroceder desde el balance actual
        for op in reversed(ops):
            if op.hora_inicio < pausa_desde:
                if op.resultado == 'win':
                    balance_inicial -= op.beneficio
                else:
                    balance_inicial += abs(op.beneficio)
        
        self.stdout.write(f"\nBalance estimado al inicio del período: ${balance_inicial:.2f}")
        
        # Avanzar operación por operación
        balance_actual = balance_inicial
        self.stdout.write(self.style.WARNING("\nRECONSTRUCCIÓN PASO A PASO:"))
        self.stdout.write("-" * 80)
        
        for op in ops:
            tiempo_relativo = (op.hora_inicio - pausa_desde).total_seconds() / 60
            
            if op.resultado == 'win':
                balance_despues = balance_actual + op.beneficio
            else:
                balance_despues = balance_actual - abs(op.beneficio)
            
            # Calcular stop loss en ese momento
            # El stop loss se basa en balance_stop_loss_base, que solo cambia en ganancias
            stop_loss_en_momento = config.calcular_stop_loss(config.balance_stop_loss_base)
            
            # Si es una ganancia, el stop loss debería subir
            if op.resultado == 'win' and balance_despues > config.balance_stop_loss_base:
                stop_loss_en_momento = config.calcular_stop_loss(balance_despues)
            
            estado = "ANTES" if tiempo_relativo < 0 else "DESPUÉS"
            color = self.style.SUCCESS if op.resultado == 'win' else self.style.ERROR
            
            self.stdout.write(f"\n{op.hora_inicio.strftime('%H:%M:%S')} | {tiempo_relativo:+.1f} min {estado} de pausa")
            self.stdout.write(f"  {op.activo} {op.direccion} | {op.resultado.upper()} | ${op.beneficio:.2f}")
            self.stdout.write(f"  Balance: ${balance_actual:.2f} → ${balance_despues:.2f}")
            self.stdout.write(f"  Stop loss en ese momento: ${stop_loss_en_momento:.2f}")
            
            if balance_actual <= stop_loss_en_momento:
                self.stdout.write(self.style.ERROR(f"  ⚠️  Balance ({balance_actual:.2f}) <= Stop Loss ({stop_loss_en_momento:.2f}) - ESTO CAUSÓ LA PAUSA"))
            elif balance_despues <= stop_loss_en_momento:
                self.stdout.write(self.style.ERROR(f"  ⚠️  Balance después ({balance_despues:.2f}) <= Stop Loss ({stop_loss_en_momento:.2f}) - ESTO CAUSÓ LA PAUSA"))
            
            balance_actual = balance_despues
        
        # Comando para buscar en logs
        self.stdout.write(self.style.WARNING("\n" + "="*80))
        self.stdout.write(self.style.WARNING("COMANDO PARA BUSCAR EN LOGS:"))
        self.stdout.write(self.style.WARNING("="*80 + "\n"))
        
        desde_str = (pausa_desde - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
        hasta_str = (pausa_desde + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
        
        self.stdout.write(f"sudo journalctl -u binabot-loop.service --since \"{desde_str}\" --until \"{hasta_str}\" --no-pager")
        self.stdout.write("\nO buscar específicamente:")
        self.stdout.write(f"sudo journalctl -u binabot-loop.service --since \"{desde_str}\" --until \"{hasta_str}\" --no-pager | grep -E \"pausa|pausado|stop|balance|sincronizar|verificar\" -i")
        
        self.stdout.write("\n")

