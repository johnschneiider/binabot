#!/usr/bin/env python
"""
Bot Deriv R_100 - Versión Liviana
Solo logs claros, sin dashboard
Uso: python bot_liviano.py --real
"""
import os
import sys
import time
import json
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
sys.path.insert(0, r'E:\Binary-bot')
django.setup()

from django.conf import settings
from gestion_riesgo.models import Cuenta, OperacionDeriv

def log(msg, color=None):
    """Log simple con timestamp"""
    ts = datetime.now().strftime('%H:%M:%S')
    colors = {
        'green': '\033[92m',
        'red': '\033[91m', 
        'yellow': '\033[93m',
        'cyan': '\033[96m',
        'end': '\033[0m'
    }
    c = colors.get(color, '')
    end = colors['end'] if c else ''
    print(f"[{ts}] {c}{msg}{end}")
    sys.stdout.flush()

def get_balance():
    """Obtiene balance actual"""
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    return cuenta.balance_deriv if cuenta else 0

def print_stats():
    """Imprime estadísticas rápidas"""
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        return
    
    balance = cuenta.balance_deriv or 0
    target = balance * 1.10
    necesita = target - balance
    
    from django.utils import timezone
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    trades = OperacionDeriv.objects.filter(cuenta=cuenta, creada_por_bot=True, updated_at__gte=today)
    
    wins = trades.filter(profit__gt=0).count()
    losses = trades.filter(profit__lt=0).count()
    total = trades.count()
    winrate = (wins/total*100) if total > 0 else 0
    profit = sum(t.profit for t in trades if t.profit)
    
    print("\n" + "="*55)
    print(f"BALANCE: ${balance:.2f}  |  TARGET: ${target:.2f}")
    print(f"WINRATE: {winrate:.0f}%  |  NECESITA: ${necesita:.2f}")
    print(f"TRADES: {total} (W:{wins} L:{losses})  |  PROFIT: ${profit:.2f}")
    print("="*55 + "\n")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', action='store_true')
    args = parser.parse_args()
    
    print("\n" + "="*55)
    print("BOT DERIV R_100 - INICIANDO")
    print("="*55)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Horario: Solo opera 20:00-21:00 UTC (15:00-16:00 Colombia)")
    print(f"Target: 10% ganancia diaria")
    print(f"Modo: {'REAL' if args.real else 'SIMULACION'}")
    print("="*55 + "\n")
    
    log("Obteniendo balance actual...", "cyan")
    balance = get_balance()
    log(f"Balance inicial: ${balance:.2f}", "green")
    
    print_stats()
    
    log("Iniciando stream de mercado...", "cyan")
    time.sleep(2)
    
    # Ejecutar bot
    from vector_variables.management.commands.deriv_stream import StreamCommand
    
    cmd = StreamCommand()
    
    # Capturar stdout para logs claros
    class SimpleLogger:
        def __init__(self, color=None):
            self.color = color
            
        def write(self, msg):
            msg = msg.strip()
            if not msg:
                return
            
            # Filtrar y colorear mensajes
            if 'CFG' in msg:
                log(msg, 'cyan')
            elif 'TRADING' in msg and ('COMPRA' in msg or 'VENTA' in msg):
                log(msg, 'green')
            elif 'SKIP' in msg or 'horario_bloqueado' in msg:
                log(msg, 'yellow')
            elif 'PROFIT' in msg or 'cerrada' in msg:
                if 'profit=-' in msg:
                    log(msg, 'red')
                else:
                    log(msg, 'green')
            elif 'ERROR' in msg or 'WARN' in msg:
                log(msg, 'red')
            elif 'BUY OK' in msg or 'SELL OK' in msg:
                log(msg, 'green')
            elif 'cap=' in msg:
                # Extraer balance del mensaje
                try:
                    parts = msg.split('cap=')
                    if len(parts) > 1:
                        cap = parts[1].split()[0]
                        bloqueado = 'True' in msg.split('bloqueado=')[1] if 'bloqueado=' in msg else False
                        status = 'BLOCKED' if bloqueado else 'ACTIVE'
                        log(f"{status} Balance: ${cap} | {msg}", None)
                except:
                    log(msg, None)
            else:
                print(msg)
            
            sys.stdout.flush()
        
        def flush(self):
            pass
    
    cmd.stdout = SimpleLogger()
    cmd.stderr = SimpleLogger()
    
    class Args:
        symbol = 'R_100'
        symbols = None
        max_ticks = 999999
        max_segundos = None
        max_reintentos = 10
        ilimitado = True
        permitir_sin_venv = True
        real = args.real
        sin_migrar = True
    
    # Contador para stats periódicos
    tick_count = 0
    
    try:
        log("Bot conectado. Esperando ticks...", "cyan")
        log("─"*55, None)
        
        # Ejecutar
        cmd.handle(**vars(Args()))
        
    except KeyboardInterrupt:
        print("\n")
        log("Deteniendo bot...", "yellow")
        print_stats()
        log("Bot detenido correctamente.", "green")
    except Exception as e:
        log(f"Error: {e}", "red")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
