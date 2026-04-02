import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

print('=== FOREX OPERACIONES ===')
from trading.models import OperacionTrading
ops = OperacionTrading.objects.all().order_by('-created_at')[:20]
print(f'Total: {OperacionTrading.objects.count()}')
for op in ops:
    ts = op.created_at.strftime('%H:%M:%S') if op.created_at else '---'
    print(f'{ts} | {op.simbolo} {op.direccion} | ent:{op.precio_entrada} | raz:{op.razon[:25]} | win:{op.es_win} | profit:{op.profit}')

wins_f = OperacionTrading.objects.filter(es_win=True).count()
total_f = OperacionTrading.objects.count()
print(f'\nFOREX WINRATE: {wins_f}/{total_f} = {wins_f/total_f*100:.1f}%' if total_f > 0 else 'Sin ops')

print('\n=== BINANCE OPERACIONES ===')
from gestion_riesgo.models import OperacionBinance
ops_b = OperacionBinance.objects.all().order_by('-created_at')[:20]
print(f'Total: {OperacionBinance.objects.count()}')
for op in ops_b:
    ts = op.created_at.strftime('%H:%M:%S') if op.created_at else '---'
    print(f'{ts} | {op.simbolo} {op.direccion} | raz:{op.razon[:25]} | win:{op.es_win}')

wins_b = OperacionBinance.objects.filter(es_win=True).count()
total_b = OperacionBinance.objects.count()
print(f'\nBINANCE WINRATE: {wins_b}/{total_b} = {wins_b/total_b*100:.1f}%' if total_b > 0 else 'Sin ops')