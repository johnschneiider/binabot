import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

from gestion_riesgo.models import OperacionBinance, EstadisticasBinance
from trading.models import BalanceGlobal
from decimal import Decimal

# 1. Borrar TODAS las operaciones Binance
count, _ = OperacionBinance.objects.all().delete()
print(f"Operaciones eliminadas: {count}")

# 2. Reiniciar estadísticas por activo
for s in EstadisticasBinance.objects.all():
    s.total_ops   = 0
    s.wins        = 0
    s.losses      = 0
    s.profit_total    = Decimal('0.00')
    s.balance_ficticio = Decimal('250.00')   # 1000 / 4 activos
    s.win_streak      = 0
    s.loss_streak     = 0
    s.max_win_streak  = 0
    s.max_loss_streak = 0
    s.save()
    print(f"  {s.simbolo} -> reseteado (balance_ficticio=250)")

print(f"Total activos reseteados: {EstadisticasBinance.objects.count()}")

# 3. Reiniciar Balance Global a 1000
bg = BalanceGlobal.get_balance()
bg.capital_ficticio  = Decimal('1000.00')
bg.profit_total      = Decimal('0.00')
bg.capital_inicial   = Decimal('1000.00')
bg.save()
print(f"Balance Global -> capital_ficticio={bg.capital_ficticio}, capital_inicial={bg.capital_inicial}")

print("RESET COMPLETADO - Comenzando desde 1000 ficticios con 0 trades")
