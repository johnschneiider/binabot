import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()
from trading.models import BalanceGlobal

bg = BalanceGlobal.get_balance()
print(f'Balance Global: ${bg.balance}')
print(f'Capital Inicial: ${bg.capital_inicial}')
print(f'Ultima actualizacion: {bg.ultima_actualizacion}')

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