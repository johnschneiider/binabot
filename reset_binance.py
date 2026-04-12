import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

from gestion_riesgo.models import OperacionBinance, EstadisticasBinance
from trading.models import BalanceGlobal
from decimal import Decimal

# ── Verificar balance REAL antes del reset ──
from dotenv import load_dotenv
load_dotenv()
import urllib.request as _ur, hmac, hashlib, time, json

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
balance_real = 0.0
if api_key and api_secret:
    try:
        ts = int(time.time() * 1000)
        q = f'timestamp={ts}'
        sig = hmac.new(api_secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        url = f'https://fapi.binance.com/fapi/v2/account?{q}&signature={sig}'
        req = _ur.Request(url, headers={'X-MBX-APIKEY': api_key})
        with _ur.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        balance_real = float(data.get('totalWalletBalance', 0))
        print(f"Balance REAL Binance: ${balance_real:.2f} USDT")
    except Exception as e:
        print(f"Error consultando balance: {e}")

# 1. Borrar TODAS las operaciones Binance
count, _ = OperacionBinance.objects.all().delete()
print(f"Operaciones eliminadas: {count}")

# 2. Reiniciar estadísticas por activo
for s in EstadisticasBinance.objects.all():
    s.total_ops        = 0
    s.wins             = 0
    s.losses           = 0
    s.profit_total     = Decimal('0.00')
    s.balance_ficticio = Decimal(str(round(balance_real, 2))) if balance_real > 0 else Decimal('10.00')
    s.win_streak       = 0
    s.loss_streak      = 0
    s.max_win_streak   = 0
    s.max_loss_streak  = 0
    s.save()
    print(f"  {s.simbolo} -> reseteado (balance={s.balance_ficticio})")

print(f"Total activos reseteados: {EstadisticasBinance.objects.count()}")

# 3. Reiniciar Balance Global al balance real de Binance
bg = BalanceGlobal.get_balance()
bal_decimal = Decimal(str(round(balance_real, 2))) if balance_real > 0 else Decimal('10.00')
bg.balance         = bal_decimal
bg.capital_inicial = bal_decimal
bg.save()
print(f"Balance Global -> balance=${bg.balance}, capital_inicial=${bg.capital_inicial}")

# 4. Limpiar ticks históricos de Binance
from gestion_riesgo.models import TickBinance
tick_count, _ = TickBinance.objects.all().delete()
print(f"Ticks eliminados: {tick_count}")

print(f"\nRESET COMPLETADO - Base de datos limpia")
print(f"Balance real Binance: ${balance_real:.2f} USDT")
print(f"Sizing dinámico: 50% × 20x = ${balance_real * 0.50 * 20:.2f} notional por op")
