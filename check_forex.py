import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

from trading.models import OperacionTrading
from gestion_riesgo.models import OperacionBinance, TickBinance
from django.db.models import Count, Q

print('=== OPERACIONES FOREX POR SÍMBOLO ===')
ops_por_simbolo = OperacionTrading.objects.values('simbolo').annotate(
    total=Count('id'),
    wins=Count('id', filter=Q(es_win=True))
).order_by('-total')

for s in ops_por_simbolo:
    wr = (s['wins']/s['total']*100) if s['total'] > 0 else 0
    print(f"{s['simbolo']}: {s['total']} ops, {s['wins']} wins, WR={wr:.1f}%")

print()
print('=== ULTIMAS 10 OPERACIONES FOREX ===')
ultimas = OperacionTrading.objects.all().order_by('-created_at')[:10]
for op in ultimas:
    print(f"{op.created_at.strftime('%H:%M:%S')} {op.simbolo} {op.direccion} => {'WIN' if op.es_win else 'LOSS'}")

print()
print('=== TICKS RECIENTES POR SÍMBOLO ===')
from trading.models import TickTrading
simbolos = ['USDJPY', 'EURUSD', 'GBPUSD', 'USDCAD', 'AUDUSD', 'NZDUSD']
for sym in simbolos:
    ticks = TickTrading.objects.filter(simbolo=sym).count()
    print(f"{sym}: {ticks} ticks")
