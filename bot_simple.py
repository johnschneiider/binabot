#!/usr/bin/env python
"""
Bot de trading simple SIN dashboard - Solo logs claros
Uso: python bot_simple.py --real
"""
import os
import sys
import time
import json
import django
from datetime import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
sys.path.insert(0, r'E:\Binary-bot')
django.setup()

import argparse
from django.conf import settings
from gestion_riesgo.models import Cuenta, OperacionDeriv, BalanceDerivSnapshot

# Colores para terminal
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print(f"""{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║           🤖 BOT DERIV R_100 - MODO SIMPLE                  ║
║           Trading Optimizado | 20:00-21:00 UTC              ║
╚══════════════════════════════════════════════════════════════╝{Colors.END}
""")

def get_status():
    """Obtiene estado actual del bot"""
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        return None
    
    # Estadísticas de hoy
    from django.utils import timezone
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    trades_today = OperacionDeriv.objects.filter(
        cuenta=cuenta, 
        creada_por_bot=True,
        updated_at__gte=today_start
    )
    
    wins = trades_today.filter(profit__gt=0).count()
    losses = trades_today.filter(profit__lt=0).count()
    total_profit = sum(t.profit for t in trades_today if t.profit)
    
    return {
        'balance': cuenta.balance_deriv or 0,
        'bloqueado': cuenta.bloqueado,
        'motivo': cuenta.riesgo_motivo,
        'trades_hoy': trades_today.count(),
        'wins': wins,
        'losses': losses,
        'winrate': (wins / trades_today.count() * 100) if trades_today.count() > 0 else 0,
        'profit_hoy': total_profit,
        'target_10pct': (cuenta.balance_deriv or 0) * 1.10,
        'necesita': ((cuenta.balance_deriv or 0) * 1.10) - (cuenta.balance_deriv or 0),
    }

def print_status(status):
    """Imprime estado formateado"""
    if not status:
        print(f"{Colors.RED}❌ No se encontró cuenta R_100{Colors.END}")
        return
    
    balance = status['balance']
    target = status['target_10pct']
    progress = (balance / target * 100) if target > 0 else 0
    
    # Color del balance
    if status['profit_hoy'] > 0:
        bal_color = Colors.GREEN
    elif status['profit_hoy'] < 0:
        bal_color = Colors.RED
    else:
        bal_color = Colors.YELLOW
    
    # Estado
    estado = f"{Colors.GREEN}✅ ACTIVO" if not status['bloqueado'] else f"{Colors.RED}⏸️ BLOQUEADO"
    
    print(f"""{Colors.WHITE}
┌─────────────────────────────────────────────────────────────┐
│ {Colors.BOLD}ESTADO ACTUAL{Colors.END}{Colors.WHITE}                                              │
├─────────────────────────────────────────────────────────────┤
│ 💰 Balance:      {bal_color}${balance:.2f}{Colors.END}                                      │
│ 🎯 Target 10%:   {Colors.CYAN}${target:.2f}{Colors.END} ({progress:.1f}%)                              │
│ 📊 Necesita:     {Colors.YELLOW}${status['necesita']:.2f}{Colors.END}                                      │
│ 🤖 Estado:       {estado}{Colors.END}                                   │
│ 📋 Motivo:       {status['motivo']}                                 │
├─────────────────────────────────────────────────────────────┤
│ {Colors.BOLD}ESTADÍSTICAS HOY{Colors.END}{Colors.WHITE}                                            │
├─────────────────────────────────────────────────────────────┤
│ 🔄 Trades:       {status['trades_hoy']}                                               │
│ ✅ Wins:         {Colors.GREEN}{status['wins']}{Colors.END}                                                  │
│ ❌ Losses:       {Colors.RED}{status['losses']}{Colors.END}                                                  │
│ 📈 Winrate:      {Colors.CYAN}{status['winrate']:.1f}%{Colors.END}                                            │
│ 💵 Profit Hoy:   {Colors.GREEN if status['profit_hoy'] >= 0 else Colors.RED}${status['profit_hoy']:.2f}{Colors.END}                                         │
└─────────────────────────────────────────────────────────────┘{Colors.END}
""")

def print_trade_log(msg):
    """Imprime log de trading"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"{Colors.BLUE}[{timestamp}]{Colors.END} {msg}")

def main():
    parser = argparse.ArgumentParser(description='Bot Deriv Simple')
    parser.add_argument('--real', action='store_true', help='Modo real')
    args = parser.parse_args()
    
    clear_screen()
    print_header()
    print(f"{Colors.YELLOW}⏳ Iniciando bot...{Colors.END}\n")
    
    # Importar y ejecutar el bot
    from vector_variables.management.commands.deriv_stream import StreamCommand
    
    # Crear comando
    cmd = StreamCommand()
    cmd.stdout = type('obj', (object,), {
        'write': lambda x: print_trade_log(x.strip()),
        'flush': lambda: None
    })()
    cmd.stderr = type('obj', (object,), {
        'write': lambda x: print_trade_log(f"{Colors.RED}{x.strip()}{Colors.END}"),
        'flush': lambda: None
    })()
    
    # Configurar argumentos
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
    
    args_obj = Args()
    
    # Ejecutar en hilo separado para poder mostrar status periódicamente
    import threading
    
    bot_running = True
    
    def run_bot():
        try:
            cmd.handle(**vars(args_obj))
        except Exception as e:
            print_trade_log(f"{Colors.RED}Error: {e}{Colors.END}")
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Mostrar status cada 30 segundos
    try:
        while True:
            time.sleep(30)
            clear_screen()
            print_header()
            status = get_status()
            print_status(status)
            print(f"\n{Colors.CYAN}🔄 Actualizando en 30 segundos... (Ctrl+C para salir){Colors.END}\n")
            
            # Mostrar últimos logs
            log_file = os.path.join(settings.BASE_DIR, 'logs', 'runtime.log')
            if os.path.exists(log_file):
                print(f"{Colors.WHITE}📋 ÚLTIMOS LOGS:{Colors.END}")
                print("─" * 60)
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-15:]
                    for line in lines:
                        line = line.strip()
                        if 'TRADING' in line or 'COMPRA' in line or 'VENTA' in line:
                            print(f"{Colors.GREEN}{line}{Colors.END}")
                        elif 'SKIP' in line or 'horario_bloqueado' in line:
                            print(f"{Colors.YELLOW}{line}{Colors.END}")
                        elif 'ERROR' in line or 'WARN' in line:
                            print(f"{Colors.RED}{line}{Colors.END}")
                        elif 'CFG' in line:
                            print(f"{Colors.CYAN}{line}{Colors.END}")
                        else:
                            print(line)
                print("─" * 60)
                
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}🛑 Deteniendo bot...{Colors.END}")
        sys.exit(0)

if __name__ == '__main__':
    main()
