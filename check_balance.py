import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()
from trading.models import BalanceGlobal

bg = BalanceGlobal.get_balance()
print(f'Balance Global (Django): ${bg.balance}')
print(f'Capital Inicial: ${bg.capital_inicial}')
print(f'Ultima actualizacion: {bg.ultima_actualizacion}')

# ── Balance REAL de Binance Futures ──
from dotenv import load_dotenv
load_dotenv()
import urllib.request as _ur, hmac, hashlib, time, json

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
if api_key and api_secret:
    try:
        ts = int(time.time() * 1000)
        q = f'timestamp={ts}'
        sig = hmac.new(api_secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        url = f'https://fapi.binance.com/fapi/v2/account?{q}&signature={sig}'
        req = _ur.Request(url, headers={'X-MBX-APIKEY': api_key})
        with _ur.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        print(f'\n--- BALANCE REAL BINANCE FUTURES ---')
        print(f'Wallet:      ${float(data.get("totalWalletBalance", 0)):.2f} USDT')
        print(f'Disponible:  ${float(data.get("availableBalance", 0)):.2f} USDT')
        print(f'PnL abierto: ${float(data.get("totalUnrealizedProfit", 0)):+.2f} USDT')
        positions = [p for p in data.get('positions', []) if float(p.get('positionAmt', 0)) != 0]
        if positions:
            print(f'Posiciones:  {len(positions)}')
            for p in positions:
                print(f'  {p["symbol"]}: qty={p["positionAmt"]} PnL=${p["unrealizedProfit"]}')
    except Exception as e:
        print(f'\nError consultando Binance: {e}')
else:
    print('\nBINANCE_API_KEY/SECRET no configurados en .env')

# Ver operaciones
from trading.models import OperacionTrading
from gestion_riesgo.models import OperacionBinance

print(f'\nFOREX: {OperacionTrading.objects.count()} ops')
print(f'BINANCE: {OperacionBinance.objects.count()} ops')

# Calcular profit total
profit_forex = sum(float(op.profit) for op in OperacionTrading.objects.all())
profit_bin = sum(float(op.profit) for op in OperacionBinance.objects.all())
print(f'\nProfit Forex: ${profit_forex:.2f}')
print(f'Profit Binance: ${profit_bin:.2f}')
print(f'Profit Total: ${profit_forex + profit_bin:.2f}')

# Calcular winrate
wins_f = OperacionTrading.objects.filter(es_win=True).count()
total_f = OperacionTrading.objects.count()
wins_b = OperacionBinance.objects.filter(es_win=True).count()
total_b = OperacionBinance.objects.count()
print(f'\nFOREX WR: {wins_f}/{total_f} = {wins_f/total_f*100:.1f}%' if total_f > 0 else 'Sin ops')
print(f'BINANCE WR: {wins_b}/{total_b} = {wins_b/total_b*100:.1f}%' if total_b > 0 else 'Sin ops')