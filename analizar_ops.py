import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'quant_deriv_bot.settings'
django.setup()

from gestion_riesgo.models import OperacionBinance
from collections import defaultdict

ops = list(OperacionBinance.objects.order_by('created_at'))
total = len(ops)
wins = sum(1 for o in ops if o.es_win)
losses = total - wins
wr = wins / total * 100 if total else 0

print(f"\n{'='*55}")
print(f"  ANALISIS {total} OPERACIONES")
print(f"  WR Global: {wr:.1f}%  ({wins}W / {losses}L)")
print(f"{'='*55}\n")

# WR por simbolo
print("── WR POR SIMBOLO ──")
by_sym = defaultdict(lambda: [0,0])
for o in ops:
    by_sym[o.simbolo][0] += 1
    if o.es_win: by_sym[o.simbolo][1] += 1
for sym, (t, w) in sorted(by_sym.items()):
    print(f"  {sym}: {w/t*100:.1f}%  ({w}W/{t-w}L  de {t})")

# WR por dirección
print("\n── WR POR DIRECCION ──")
by_dir = defaultdict(lambda: [0,0])
for o in ops:
    by_dir[o.direccion][0] += 1
    if o.es_win: by_dir[o.direccion][1] += 1
for d, (t, w) in sorted(by_dir.items()):
    print(f"  {d}: {w/t*100:.1f}%  ({w}W/{t-w}L  de {t})")

# WR por hora UTC
print("\n── WR POR HORA UTC ──")
by_hour = defaultdict(lambda: [0,0])
for o in ops:
    h = o.created_at.hour
    by_hour[h][0] += 1
    if o.es_win: by_hour[h][1] += 1
for h in sorted(by_hour.keys()):
    t, w = by_hour[h]
    bar = '█' * w + '░' * (t-w)
    print(f"  {h:02d}h: {w/t*100:.0f}%  {bar}  ({w}W/{t-w}L)")

# Detectar rachas
print("\n── RACHAS ──")
racha_actual = 1
tipo_racha = 'W' if ops[0].es_win else 'L'
rachas = []
for i in range(1, len(ops)):
    tipo = 'W' if ops[i].es_win else 'L'
    if tipo == tipo_racha:
        racha_actual += 1
    else:
        rachas.append((tipo_racha, racha_actual, ops[i-racha_actual].simbolo, ops[i-racha_actual].created_at.strftime('%H:%M')))
        tipo_racha = tipo
        racha_actual = 1
rachas.append((tipo_racha, racha_actual, ops[-racha_actual].simbolo, ops[-racha_actual].created_at.strftime('%H:%M')))

max_win_streak = max((r[1] for r in rachas if r[0]=='W'), default=0)
max_loss_streak = max((r[1] for r in rachas if r[0]=='L'), default=0)
print(f"  Racha max WIN:  {max_win_streak}")
print(f"  Racha max LOSS: {max_loss_streak}")
print(f"\n  Detalle rachas (>2):")
for tipo, n, sym, hora in rachas:
    if n >= 2:
        emoji = '✅' if tipo == 'W' else '❌'
        print(f"    {emoji} x{n}  desde {hora}  ({sym})")

# Análisis precio entrada vs salida (profit)
print("\n── PROFIT POR OPERACION (últimas 15) ──")
for o in ops[-15:]:
    result = '✅' if o.es_win else '❌'
    print(f"  {result} {o.simbolo} {o.direccion}  profit:{float(o.profit):+.2f}  {o.created_at.strftime('%H:%M:%S')}  {o.razon[:40] if o.razon else ''}")

# Consecutivos loss -> contexto
print("\n── CONTEXTO DE PERDIDAS ──")
for i, o in enumerate(ops):
    if not o.es_win:
        prev = ops[i-1] if i > 0 else None
        sig  = ops[i+1] if i < len(ops)-1 else None
        print(f"  ❌ #{i+1} {o.simbolo} {o.direccion} | razon: {o.razon[:50] if o.razon else 'N/A'}")
        if prev:
            p = '✅' if prev.es_win else '❌'
            print(f"      Anterior: {p} {prev.simbolo} {prev.direccion}")
        if sig:
            s = '✅' if sig.es_win else '❌'
            print(f"      Siguiente: {s} {sig.simbolo} {sig.direccion}")
