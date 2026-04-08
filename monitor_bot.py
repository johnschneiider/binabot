"""
Bot de Trading - Monitoreo de 6 horas
KPI: >80% Win Rate operando en dinero real
"""
import subprocess
import sys
import os
import time
import threading
import signal

# Keep track of processes
processes = []

def signal_handler(sig, frame):
    print('\n[STOP] Deteniendo todos los procesos...')
    for p in processes:
        try:
            p.terminate()
        except:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def monitor_balance():
    """Monitor balance every 30 seconds"""
    import requests
    import hmac
    import hashlib
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    while True:
        try:
            ts = int(time.time() * 1000)
            sig = hmac.new(api_secret.encode(), f'timestamp={ts}'.encode(), hashlib.sha256).hexdigest()
            r = requests.get(f'https://fapi.binance.com/fapi/v2/account?timestamp={ts}&signature={sig}', 
                           headers={'X-MBX-APIKEY': api_key}, timeout=5)
            data = r.json()
            bal = float(data.get('availableBalance', 0))
            print(f'\n>>> BALANCE ACTUAL: ${bal:.2f} USDT | Tiempo: {int(time.time() - start_time)/60:.0f} min')
        except Exception as e:
            print(f'\n>>> Error balance: {e}')
        time.sleep(30)

# Start Django
print("[1] Iniciando Django...")
django_proc = subprocess.Popen(
    [sys.executable, 'manage.py', 'runserver', '8000'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1
)
processes.append(django_proc)

# Wait for Django to start
time.sleep(5)

# Start bot
print("[2] Iniciando Bot...")
bot_proc = subprocess.Popen(
    [sys.executable, 'binance_bot_django.py'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1
)
processes.append(bot_proc)

# Start balance monitor thread
start_time = time.time()
monitor_thread = threading.Thread(target=monitor_balance, daemon=True)
monitor_thread.start()

print("\n" + "="*60)
print("  MONITOREO DE BOT - 6 HORAS")
print("  KPI: >80% Win Rate | Balance Real")
print("="*60)

# Log output
trade_count = 0
win_count = 0

try:
    while True:
        line = bot_proc.stdout.readline()
        if not line:
            break
        
        print(line, end='')
        
        # Track trades
        if 'ENTRADA' in line:
            trade_count += 1
            print(f'\n*** TRADE #{trade_count} ***')
        if 'WIN' in line:
            win_count += 1
            wr = (win_count / trade_count * 100) if trade_count > 0 else 0
            print(f'*** WIN! WR: {wr:.1f}% ***\n')
        if 'LOSS' in line:
            wr = (win_count / trade_count * 100) if trade_count > 0 else 0
            print(f'*** LOSS. WR: {wr:.1f}% ***\n')
        
        # Check if 6 hours elapsed
        elapsed = time.time() - start_time
        if elapsed >= 6 * 3600:
            print("\n[COMPLETO] 6 horas completadas!")
            break
            
except KeyboardInterrupt:
    print("\n[STOP] Interrumpido por usuario")
finally:
    for p in processes:
        try:
            p.terminate()
        except:
            pass
    
    print("\n" + "="*60)
    print("  RESUMEN FINAL")
    print("="*60)
    print(f"Total trades: {trade_count}")
    print(f"Wins: {win_count}")
    print(f"Losses: {trade_count - win_count}")
    wr = (win_count / trade_count * 100) if trade_count > 0 else 0
    print(f"Win Rate: {wr:.1f}%")
    print(f"Duración: {elapsed/3600:.1f} horas")
