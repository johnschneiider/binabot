from gestion_riesgo.models import OperacionBinance

qs = OperacionBinance.objects.filter(orden_real=True).order_by('-created_at')[:10]
print('id | simbolo | dir | profit | win | fecha')
total = 0
wins = 0
for op in qs:
    print(op.id, op.simbolo, op.direccion, op.profit, op.es_win, op.created_at)
    total += float(op.profit)
    wins += int(op.es_win)
print('---\nNeto:', total, '| Wins:', wins, '/', len(qs))
