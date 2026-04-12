"""
BACKTEST — FRANCOTIRADOR v4 (MOMENTUM SNIPER)
Simula la estrategia v4 con early take-profit usando datos de 1m.

La idea: con 1m candles podemos simular si el precio alcanzó el TP
en los siguientes 1-2 minutos mirando high/low de las velas.
"""
import csv
import os
import statistics
from datetime import datetime
from dataclasses import dataclass

# ── PARÁMETROS v4 ──
TAKE_PROFIT_PCT = 0.020    # 0.020% take profit
STOP_LOSS_PCT = 0.12       # 0.12% stop loss
DURACION_VELAS = 1         # 1 vela de 1m
ADX_MIN = 22.0
EMA_GAP_PCT = 0.06
RSI_CALL_MAX = 58.0
RSI_PUT_MIN = 42.0
MOMENTUM_MIN_PCT = 0.04    # Momentum MUY fuerte
TICK_CONSISTENCY_MIN = 0.75  # 75%+ consistencia
WARMUP = 60
COOLDOWN = 10
STAKE = 1.0
PAYOUT = 0.95

# ── INDICADORES ──
def ema(precios, n):
    if len(precios) < n: return None
    a = 2.0 / (n + 1.0)
    e = sum(precios[:n]) / n
    for p in precios[n:]:
        e = a * p + (1 - a) * e
    return e

def rsi(cierres, n=14):
    if len(cierres) < n + 1: return 50.0
    seg = cierres[-(n+1):]
    cambios = [seg[i] - seg[i-1] for i in range(1, len(seg))]
    g = sum(max(c, 0) for c in cambios) / n
    p = sum(max(-c, 0) for c in cambios) / n
    if p == 0: return 100.0
    return 100.0 - 100.0 / (1.0 + g / p)

def adx_calc(precios, n=14):
    if len(precios) < n + 2: return 0.0
    seg = precios[-(n+2):]
    dm_up, dm_dn, tr_list = [], [], []
    for i in range(1, len(seg)):
        h = max(seg[i], seg[i-1])
        l = min(seg[i], seg[i-1])
        pc = seg[i-1]
        up = h - seg[i-1]; dn = seg[i-1] - l
        dm_up.append(up if up > dn and up > 0 else 0)
        dm_dn.append(dn if dn > up and dn > 0 else 0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    nn = len(dm_up)
    atr = sum(tr_list) / nn or 1
    dip = sum(dm_up) / nn / atr * 100
    dim = sum(dm_dn) / nn / atr * 100
    if dip + dim == 0: return 0.0
    return abs(dip - dim) / (dip + dim) * 100

def momentum_pct(precios, n):
    if len(precios) < n + 1: return 0.0
    base = precios[-n-1]
    if base == 0: return 0.0
    return (precios[-1] - base) / base * 100

def tick_consistency_candle(opens, closes, n=10):
    """Simulamos tick consistency con velas: % de velas que cerraron en la misma dirección"""
    if len(opens) < n or len(closes) < n: return 0.5, 0.5
    up = sum(1 for i in range(-n, 0) if closes[i] > opens[i])
    down = sum(1 for i in range(-n, 0) if closes[i] < opens[i])
    total = up + down
    if total == 0: return 0.5, 0.5
    return up / total, down / total

@dataclass
class Op:
    idx: int
    dir: str
    entrada: float
    es_win: bool = False
    salida: float = 0.0
    motivo: str = ""

def cargar_csv(path):
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row.get('volume', 0)),
                'timestamp': row.get('timestamp', ''),
            })
    return rows

def backtest(candles, symbol):
    cierres = []
    opens_list = []
    ops = []
    cooldown = 0
    cooldown_mult = 1.0
    MAX_WINDOW = 100  # Only keep last 100 candles for indicators

    for i, c in enumerate(candles):
        cierres.append(c['close'])
        opens_list.append(c['open'])
        # Trim to avoid O(n^2)
        if len(cierres) > MAX_WINDOW:
            cierres = cierres[-MAX_WINDOW:]
            opens_list = opens_list[-MAX_WINDOW:]

        if cooldown > 0:
            cooldown -= 1
            continue

        if len(cierres) < WARMUP:
            continue

        # Indicadores
        e5 = ema(cierres[-30:], 5)
        e13 = ema(cierres[-40:], 13)
        e21 = ema(cierres[-50:], 21)
        if e5 is None or e13 is None or e21 is None:
            continue

        rsi_val = rsi(cierres)
        adx_val = adx_calc(cierres)
        mom5 = momentum_pct(cierres, 5)
        mom10 = momentum_pct(cierres, 10)
        mom20 = momentum_pct(cierres, 20)
        gap = abs(e5 - e21) / e21 * 100

        pct_up, pct_down = tick_consistency_candle(opens_list, cierres, 10)

        # Aceleración (mom reciente vs previo)
        mom_prev = momentum_pct(cierres[:-5], 5) if len(cierres) > 10 else 0
        accel = mom5 - mom_prev

        if adx_val < ADX_MIN: continue
        if gap < EMA_GAP_PCT: continue

        # CALL
        call_ok = (
            e5 > e13 > e21
            and rsi_val < RSI_CALL_MAX and rsi_val > 35
            and mom5 > MOMENTUM_MIN_PCT
            and mom10 > 0 and mom20 > 0
            and pct_up >= TICK_CONSISTENCY_MIN
            and accel > 0.001
        )

        # PUT
        put_ok = (
            e5 < e13 < e21
            and rsi_val > RSI_PUT_MIN and rsi_val < 65
            and mom5 < -MOMENTUM_MIN_PCT
            and mom10 < 0 and mom20 < 0
            and pct_down >= TICK_CONSISTENCY_MIN
            and accel < -0.001
        )

        if not call_ok and not put_ok:
            continue

        direction = "CALL" if call_ok else "PUT"
        entry = c['close']

        # Simular early exit mirando las siguientes velas
        es_win = False
        motivo = "expiry"
        salida = entry

        remaining = min(DURACION_VELAS, len(candles) - i - 1)
        for j in range(1, remaining + 1):
            future = candles[i + j]

            if direction == "CALL":
                # Check TP: high de la vela alcanzó entry * (1 + TP%)
                tp_price = entry * (1 + TAKE_PROFIT_PCT / 100)
                sl_price = entry * (1 - STOP_LOSS_PCT / 100)
                if future['high'] >= tp_price:
                    es_win = True
                    salida = tp_price
                    motivo = "TP"
                    break
                if future['low'] <= sl_price:
                    es_win = False
                    salida = sl_price
                    motivo = "SL"
                    break
            else:  # PUT
                tp_price = entry * (1 - TAKE_PROFIT_PCT / 100)
                sl_price = entry * (1 + STOP_LOSS_PCT / 100)
                if future['low'] <= tp_price:
                    es_win = True
                    salida = tp_price
                    motivo = "TP"
                    break
                if future['high'] >= sl_price:
                    es_win = False
                    salida = sl_price
                    motivo = "SL"
                    break

            # Si es la última vela (expiry), comparar cierre
            if j == remaining:
                salida = future['close']
                if direction == "CALL":
                    es_win = salida > entry
                else:
                    es_win = salida < entry
                motivo = "expiry"

        ops.append(Op(idx=i, dir=direction, entrada=entry, es_win=es_win,
                       salida=salida, motivo=motivo))

        # Cooldown
        if es_win:
            cooldown_mult = max(1.0, cooldown_mult / 2)
        else:
            cooldown_mult = min(8.0, cooldown_mult * 2)
        cooldown = int(COOLDOWN * cooldown_mult)

    return ops

def main():
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    files = [
        ('BTCUSDT', 'BTCUSDT_1m.csv'),
        ('ETHUSDT', 'ETHUSDT_1m.csv'),
        ('SOLUSDT', 'SOLUSDT_1m.csv'),
    ]

    total_wins = 0
    total_ops = 0
    total_profit = 0

    for symbol, fname in files:
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            print(f"[SKIP] {path} no existe")
            continue

        candles = cargar_csv(path)
        print(f"\n{'='*55}")
        print(f"  {symbol} — {len(candles)} velas de 1m")
        print(f"{'='*55}")

        ops = backtest(candles, symbol)
        if not ops:
            print("  Sin operaciones")
            continue

        wins = sum(1 for o in ops if o.es_win)
        losses = len(ops) - wins
        wr = wins / len(ops) * 100
        pnl = sum(STAKE * PAYOUT if o.es_win else -STAKE for o in ops)

        tp_count = sum(1 for o in ops if o.motivo == "TP")
        sl_count = sum(1 for o in ops if o.motivo == "SL")
        exp_count = sum(1 for o in ops if o.motivo == "expiry")

        calls = [o for o in ops if o.dir == "CALL"]
        puts = [o for o in ops if o.dir == "PUT"]
        call_wr = sum(1 for o in calls if o.es_win) / len(calls) * 100 if calls else 0
        put_wr = sum(1 for o in puts if o.es_win) / len(puts) * 100 if puts else 0

        total_wins += wins
        total_ops += len(ops)
        total_profit += pnl

        print(f"  Operaciones: {len(ops)} ({wins}W / {losses}L)")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  CALL: {len(calls)} ops, WR {call_wr:.1f}%")
        print(f"  PUT:  {len(puts)} ops, WR {put_wr:.1f}%")
        print(f"  Cierres: TP={tp_count} | SL={sl_count} | Expiry={exp_count}")
        print(f"  P&L: ${pnl:+.2f}")

        # Últimas 10 ops
        print(f"\n  Últimas {min(10, len(ops))} operaciones:")
        for o in ops[-10:]:
            r = "WIN" if o.es_win else "LOSS"
            chg = (o.salida - o.entrada) / o.entrada * 100
            print(f"    #{o.idx} {o.dir} {r} ({o.motivo}) | {o.entrada:.2f}→{o.salida:.2f} ({chg:+.4f}%)")

    if total_ops > 0:
        print(f"\n{'='*55}")
        print(f"  RESUMEN GLOBAL")
        print(f"{'='*55}")
        print(f"  Total ops: {total_ops}")
        print(f"  Win Rate: {total_wins/total_ops*100:.1f}%")
        print(f"  P&L Total: ${total_profit:+.2f}")
        print(f"{'='*55}")

if __name__ == "__main__":
    main()
