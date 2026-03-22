"""
Backtest 24h - USA TODOS los ticks disponibles (66K+)
Prueba todas las horas UTC con múltiples duraciones
"""
import os, sys
from datetime import datetime, timezone
from collections import deque

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import TickDerivHistorico
from vector_pesos.senal_spp import _alpha, _slope


def run_backtest():
    print("=" * 80)
    print("BACKTEST 24H - TODOS LOS TICKS DISPONIBLES")
    print("=" * 80)

    ticks_qs = TickDerivHistorico.objects.order_by('epoch')
    total = ticks_qs.count()
    print(f"Ticks cargados: {total:,}")

    epochs = list(ticks_qs.values_list('epoch', flat=True))
    precios = list(ticks_qs.values_list('precio', flat=True))

    dt_ini = datetime.fromtimestamp(epochs[0], tz=timezone.utc)
    dt_fin = datetime.fromtimestamp(epochs[-1], tz=timezone.utc)
    print(f"Desde: {dt_ini} UTC")
    print(f"Hasta: {dt_fin} UTC")
    print()

    payout = 0.85
    breakeven = 1 / (1 + payout)
    stake = 1.0

    configs = [
        {"ema_fast": 5, "ema_slow": 13, "gap": 0.20, "slope": 0.15},
        {"ema_fast": 5, "ema_slow": 13, "gap": 0.25, "slope": 0.20},
        {"ema_fast": 5, "ema_slow": 13, "gap": 0.30, "slope": 0.25},
        {"ema_fast": 8, "ema_slow": 21, "gap": 0.25, "slope": 0.20},
        {"ema_fast": 8, "ema_slow": 21, "gap": 0.30, "slope": 0.25},
    ]
    duraciones = [5, 10, 15, 20, 25]

    signals = []
    skipped = 0

    for cfg in configs:
        ef = cfg["ema_fast"]
        es = cfg["ema_slow"]
        gap_min = cfg["gap"]
        slope_min = cfg["slope"]

        a_fast = _alpha(ef)
        a_slow = _alpha(es)

        ema_fast_val = None
        ema_slow_val = None
        ema_hist = deque(maxlen=64)
        cooldown = 0

        for i in range(len(precios)):
            precio = float(precios[i])
            epoch = epochs[i]
            dt_utc = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            hora_utc = dt_utc.hour

            if ema_fast_val is None:
                ema_fast_val = precio
                ema_slow_val = precio
            else:
                ema_fast_val = precio * a_fast + ema_fast_val * (1 - a_fast)
                ema_slow_val = precio * a_slow + ema_slow_val * (1 - a_slow)

            ema_hist.append(ema_fast_val)

            if cooldown > 0:
                cooldown -= 1
                continue

            gap = ema_fast_val - ema_slow_val
            slope_val = _slope(ema_hist, ef)
            if slope_val is None:
                continue

            if abs(gap) < gap_min or abs(slope_val) < slope_min:
                skipped += 1
                continue

            direccion = "CALL" if gap > 0 else "PUT"

            for dur in duraciones:
                signals.append({
                    "idx": i,
                    "hora_utc": hora_utc,
                    "cfg": cfg,
                    "dur": dur,
                    "precio_entrada": precio,
                    "direccion": direccion,
                })

            cooldown = 5

    print(f"Total señales generadas: {len(signals):,}")
    print(f"Signales saltadas (no cumplen filtros): {skipped:,}")
    print()
    print(f"Payout: {payout} | Breakeven: {breakeven*100:.2f}%")
    print("=" * 80)

    for sig in signals:
        dur = sig["dur"]
        idx = sig["idx"]
        precio_entrada = sig["precio_entrada"]
        direccion = sig["direccion"]

        win = False
        if idx + dur < len(precios):
            precio_salida = float(precios[idx + dur])
            diff = precio_salida - precio_entrada
            if (direccion == "CALL" and diff > 0) or (direccion == "PUT" and diff < 0):
                win = True

        sig["win"] = win

    all_summary = []

    for cfg in configs:
        label = f"EMA({cfg['ema_fast']},{cfg['ema_slow']}) gap>{cfg['gap']} slope>{cfg['slope']}"
        print()
        print(f"CONFIG: {label}")
        print("-" * 80)

        cfg_signals = [s for s in signals if s["cfg"] == cfg]

        for dur in duraciones:
            hour_data = {}
            for h in range(24):
                hrs = [s for s in cfg_signals if s["hora_utc"] == h and s["dur"] == dur]
                if len(hrs) < 3:
                    continue

                wins = sum(1 for s in hrs if s["win"])
                wr = wins / len(hrs)
                edge = wr - breakeven
                profit_total = wins * stake * payout - (len(hrs) - wins) * stake
                h_col = (h - 5) % 24

                if edge > 0.02 and len(hrs) >= 5:
                    all_summary.append({
                        "hora_utc": h,
                        "hora_col": h_col,
                        "cfg_label": label,
                        "cfg": cfg,
                        "dur": dur,
                        "wr": wr,
                        "edge": edge,
                        "profit": profit_total,
                        "trades": len(hrs),
                        "wins": wins,
                        "losses": len(hrs) - wins,
                    })

    print()
    print("=" * 80)
    print(f"RESUMEN - CONFIGURACIONES CON EDGE > 2% y min 5 trades")
    print(f"{'#':<3} {'HORA COL':>9} {'CONFIG':>28} {'DUR':>4} {'TRADES':>6} {'W/L':>7} {'WR%':>6} {'EDGE%':>7} {'PROFIT':>8}")
    print("-" * 80)

    all_summary.sort(key=lambda x: (-x["edge"], -x["trades"]))
    for i, s in enumerate(all_summary[:25]):
        print(f"{i+1:<3} {s['hora_col']:02d}:00 COL  {s['cfg_label']:>28}  {s['dur']:>4}  {s['trades']:>6}  {s['wins']}/{s['losses']}  {s['wr']*100:>5.1f}%  {s['edge']*100:>+6.1f}%  ${s['profit']:>+7.2f}")

    print()
    print("=" * 80)
    print("MEJORES 10 POR EDGE+TRADES (TABLA COMPLETA)")
    print("=" * 80)
    for i, s in enumerate(all_summary[:10]):
        print(f"\n#{i+1}: {s['hora_col']:02d}:00 COL = {s['hora_utc']:02d}:00 UTC")
        print(f"   {s['cfg_label']} | dur={s['dur']}")
        print(f"   WR: {s['wr']*100:.1f}% | Edge: {s['edge']*100:+.1f}% | Profit: ${s['profit']:.2f} | Trades: {s['trades']} ({s['wins']}W/{s['losses']}L)")

    print()
    print("=" * 80)
    print("HORAS A EVITAR (edge < -10%)")
    print("=" * 80)
    avoid = set()
    for cfg in configs:
        label = f"EMA({cfg['ema_fast']},{cfg['ema_slow']}) gap>{cfg['gap']}"
        cfg_signals = [s for s in signals if s["cfg"] == cfg]
        for dur in [10, 15, 20]:
            bad = []
            for h in range(24):
                hrs = [s for s in cfg_signals if s["hora_utc"] == h and s["dur"] == dur]
                if len(hrs) < 5:
                    continue
                wins = sum(1 for s in hrs if s["win"])
                wr = wins / len(hrs)
                edge = wr - breakeven
                if edge < -0.10:
                    h_col = (h - 5) % 24
                    bad.append((h, h_col, edge, wr, len(hrs)))
                    avoid.add(h_col)
            if bad:
                print(f"  {label} dur={dur}:")
                for h, hc, edge, wr, n in sorted(bad, key=lambda x: x[2]):
                    print(f"    {hc:02d}:00 COL | WR:{wr*100:.1f}% | Edge:{edge*100:.1f}% | Trades:{n}")

    print()
    print("=" * 80)
    print("RECOMENDACIONES PARA .env")
    print("=" * 80)
    if all_summary:
        top = all_summary[0]
        good_hours = sorted(set(s["hora_col"] for s in all_summary if s["edge"] > 0.05))
        block_hours = [h for h in range(24) if h not in good_hours]

        print(f"Horas buenas (edge>5%): {', '.join(f'{h:02d}' for h in good_hours)}")
        print(f"Horas a bloquear: {', '.join(f'{h:02d}' for h in block_hours)}")
        print()
        print(f"MEJOR CONFIG:")
        print(f"  Hora: {top['hora_col']:02d}:00 COL = {top['hora_utc']:02d}:00 UTC")
        print(f"  {top['cfg_label']}")
        print(f"  Duracion: {top['dur']} ticks")
        print(f"  WR esperado: {top['wr']*100:.1f}%")
        print(f"  Edge: +{top['edge']*100:.1f}%")
        print(f"  Profit backtest: ${top['profit']:.2f}")


if __name__ == "__main__":
    run_backtest()
