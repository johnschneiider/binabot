"""
BACKTEST — SNIPER PULLBACK v2.0
Estrategia multi-timeframe: 15m EMA50 + 5m ADX + 1m RSI pullback.
"""

import json
import time
import statistics
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
import urllib.request

# ============================================================
#  PARÁMETROS
# ============================================================

STAKE             = 1.0
PAYOUT            = 0.95
DURACION_VELAS    = 15         # Hold = 15 min (capturar momentum real)
ADX_MIN           = 28         # Solo mercados fuertemente trending
ADX_PERIODO       = 14
RSI_PERIODO       = 14
EMA50_SLOPE_N     = 5
EMA50_SLOPE_MIN   = 0.03       # Pendiente minima % del 15m EMA50 (filtra flat markets)
RSI_PULLBACK_CALL = 42         # Pullback profundo requerido
RSI_PULLBACK_PUT  = 58         # Pullback profundo requerido
RSI_RESUME_CALL   = 50
RSI_RESUME_PUT    = 50
WARMUP_CANDLES    = 30
MAX_OPS_DIA       = 10         # Calidad sobre cantidad
COOLDOWN_VELAS    = 10         # 10 min cooldown entre trades
VOL_FILTER_RATIO  = 0.8        # Volumen minimo = 80% del promedio 20-periodos

# ============================================================
#  INDICADORES
# ============================================================

def ema_lista(precios: list, periodo: int) -> list:
    if len(precios) < periodo:
        return [None] * len(precios)
    alpha = 2.0 / (periodo + 1.0)
    emas  = [None] * (periodo - 1)
    emas.append(sum(precios[:periodo]) / periodo)
    for p in precios[periodo:]:
        emas.append(alpha * p + (1 - alpha) * emas[-1])
    return emas


def calc_rsi(cierres: list, n: int = 14) -> float:
    if len(cierres) < n + 1:
        return 50.0
    seg = cierres[-(n + 1):]
    cambios = [seg[i] - seg[i - 1] for i in range(1, len(seg))]
    ag = sum(max(c, 0) for c in cambios) / n
    ap = sum(max(-c, 0) for c in cambios) / n
    if ap == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / ap))


def calc_adx(highs: list, lows: list, closes: list, n: int = 14) -> float:
    if len(closes) < n + 2:
        return 0.0
    hs, ls, cs = highs[-(n+1):], lows[-(n+1):], closes[-(n+1):]
    dm_up, dm_dn, atr_l = [], [], []
    for i in range(1, len(cs)):
        h, l, pc = hs[i], ls[i], cs[i - 1]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        up  = h - hs[i - 1]
        dn  = ls[i - 1] - l
        dm_up.append(up if (up > dn and up > 0) else 0)
        dm_dn.append(dn if (dn > up and dn > 0) else 0)
        atr_l.append(tr)
    atr = sum(atr_l) / n or 1
    dip = sum(dm_up) / n / atr * 100
    dim = sum(dm_dn) / n / atr * 100
    return 0.0 if dip + dim == 0 else abs(dip - dim) / (dip + dim) * 100

# ============================================================
#  DESCARGA DE DATOS
# ============================================================

def descargar_klines(simbolo: str, intervalo: str, dias: int, limit_max: int = 1000) -> list:
    print(f"Descargando {simbolo} {intervalo} ({dias} días)...")
    end_ms    = int(time.time() * 1000)
    start_ms  = end_ms - dias * 86400 * 1000
    base_url  = "https://api.binance.com/api/v3/klines"
    all_data  = []
    current   = start_ms

    while current < end_ms:
        url = f"{base_url}?symbol={simbolo}&interval={intervalo}&startTime={current}&limit={limit_max}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            if not data:
                break
            all_data.extend(data)
            current = data[-1][0] + 1
            time.sleep(0.08)
        except Exception as e:
            print(f"  Error descarga: {e}")
            break

    print(f"  {len(all_data)} velas OK")
    return all_data

# ============================================================
#  BACKTEST MULTI-TIMEFRAME
# ============================================================

@dataclass
class Operacion:
    idx:    int
    dir:    str
    entrada: float
    salida:  float = 0.0
    win:     bool  = False
    profit:  float = 0.0


def run_backtest(simbolo: str = "BTCUSDT", dias: int = 14):
    """
    Descarga datos y ejecuta el backtest de la estrategia Sniper Pullback.
    """
    raw_1m  = descargar_klines(simbolo, "1m",  dias)
    raw_5m  = descargar_klines(simbolo, "5m",  dias)
    raw_15m = descargar_klines(simbolo, "15m", dias)

    if len(raw_1m) < 100:
        print("Insuficientes datos 1m")
        return

    # Extracción de OHLC
    ts_1m   = [int(c[0])    for c in raw_1m]
    o_1m    = [float(c[1])  for c in raw_1m]
    h_1m    = [float(c[2])  for c in raw_1m]
    l_1m    = [float(c[3])  for c in raw_1m]
    c_1m    = [float(c[4])  for c in raw_1m]
    vol_1m  = [float(c[5])  for c in raw_1m]   # volumen base

    h_5m    = [float(c[2])  for c in raw_5m]
    l_5m    = [float(c[3])  for c in raw_5m]
    c_5m    = [float(c[4])  for c in raw_5m]
    ts_5m   = [int(c[0])    for c in raw_5m]

    c_15m   = [float(c[4])  for c in raw_15m]
    ts_15m  = [int(c[0])    for c in raw_15m]

    # Pre-computar EMA50 en 15m (no cambia en el loop 1m)
    ema50_15m = ema_lista(c_15m, 50)

    def get_15m_idx(ts_1m_val):
        """Índice del candle 15m correspondiente al timestamp 1m dado."""
        for j in range(len(ts_15m) - 1, -1, -1):
            if ts_15m[j] <= ts_1m_val:
                return j
        return 0

    def get_5m_idx(ts_1m_val):
        for j in range(len(ts_5m) - 1, -1, -1):
            if ts_5m[j] <= ts_1m_val:
                return j
        return 0

    operaciones = []
    capital      = 100.0
    capital_max  = 100.0
    drawdown_max = 0.0
    ops_dia_dict = {}    # fecha → count
    pendiente    = None  # {idx_entrada, dir, precio}
    cooldown     = 0
    rsi_anterior = 50.0

    print(f"\nBacktest Sniper Pullback v2.1 — {len(c_1m)} velas 1m")
    print(f"Filtros: ADX>={ADX_MIN}, RSI pull<{RSI_PULLBACK_CALL}/>{ RSI_PULLBACK_PUT}, slope>={EMA50_SLOPE_MIN}%, vol>={VOL_FILTER_RATIO*100:.0f}%MA, hold={DURACION_VELAS}min")
    print(f"Periodo: {datetime.fromtimestamp(ts_1m[0]/1000)} -> {datetime.fromtimestamp(ts_1m[-1]/1000)}\n")

    for i in range(WARMUP_CANDLES, len(c_1m)):
        ts  = ts_1m[i]
        dia = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        ops_dia_dict.setdefault(dia, 0)

        # ── Cierre de operación pendiente ──────────────────
        if pendiente is not None:
            if i - pendiente['idx'] >= DURACION_VELAS:
                precio_salida = c_1m[i]
                es_win = (precio_salida > pendiente['precio']) if pendiente['dir'] == 'CALL' \
                         else (precio_salida < pendiente['precio'])
                profit = STAKE * PAYOUT if es_win else -STAKE
                capital += profit
                capital_max = max(capital, capital_max)
                dd = (capital_max - capital) / capital_max
                drawdown_max = max(drawdown_max, dd)
                operaciones.append(Operacion(
                    idx=i, dir=pendiente['dir'],
                    entrada=pendiente['precio'],
                    salida=precio_salida,
                    win=es_win, profit=profit
                ))
                pendiente = None
                cooldown  = COOLDOWN_VELAS

        if pendiente is not None:
            rsi_anterior = calc_rsi(c_1m[:i], RSI_PERIODO)
            continue

        if cooldown > 0:
            cooldown -= 1
            rsi_anterior = calc_rsi(c_1m[:i], RSI_PERIODO)
            continue

        if ops_dia_dict[dia] >= MAX_OPS_DIA:
            rsi_anterior = calc_rsi(c_1m[:i], RSI_PERIODO)
            continue

        # ── Calcular indicadores para esta vela ─────────────

        # 1m RSI actual vs anterior
        closes_hasta_i = c_1m[:i + 1]
        rsi_actual     = calc_rsi(closes_hasta_i, RSI_PERIODO)
        vela_alcista   = c_1m[i] > o_1m[i]
        vela_bajista   = c_1m[i] < o_1m[i]

        # Volumen filtro: comparar con media de 20 periodos anteriores
        if i >= 20:
            vol_ma20 = sum(vol_1m[i-20:i]) / 20
            vol_ok   = vol_1m[i] >= vol_ma20 * VOL_FILTER_RATIO
        else:
            vol_ok = True  # sin datos suficientes, no filtrar

        # 5m ADX
        idx_5m = get_5m_idx(ts)
        if idx_5m < ADX_PERIODO + 2:
            rsi_anterior = rsi_actual
            continue
        adx_val = calc_adx(h_5m[:idx_5m+1], l_5m[:idx_5m+1], c_5m[:idx_5m+1], ADX_PERIODO)

        # 15m EMA50 tendencia macro
        idx_15m = get_15m_idx(ts)
        e15_vals = [e for e in ema50_15m[:idx_15m+1] if e is not None]
        if len(e15_vals) < EMA50_SLOPE_N + 1:
            rsi_anterior = rsi_actual
            continue
        e_now  = e15_vals[-1]
        e_prev = e15_vals[-EMA50_SLOPE_N - 1]
        precio = c_1m[i]

        slope_pct  = (e_now - e_prev) / e_prev * 100 if e_prev else 0
        bull_macro = (slope_pct >=  EMA50_SLOPE_MIN) and (precio > e_now)
        bear_macro = (slope_pct <= -EMA50_SLOPE_MIN) and (precio < e_now)

        # 1m EMA21 micro-filtro
        ema21_1m = ema_lista(closes_hasta_i, 21)
        ema21_nones_filtered = [e for e in ema21_1m if e is not None]
        if ema21_nones_filtered:
            ema21_now = ema21_nones_filtered[-1]
            ema21_bull = precio >= ema21_now
            ema21_bear = precio <= ema21_now
        else:
            ema21_bull = ema21_bear = True  # sin datos suficientes, no filtrar

        # ── Señales ─────────────────────────────────────────
        if adx_val >= ADX_MIN and vol_ok:
            pullback_call = (rsi_anterior < RSI_PULLBACK_CALL) and (rsi_actual > RSI_RESUME_CALL)
            pullback_put  = (rsi_anterior > RSI_PULLBACK_PUT)  and (rsi_actual < RSI_RESUME_PUT)

            if bull_macro and pullback_call and vela_alcista and ema21_bull:
                pendiente = {'idx': i, 'dir': 'CALL', 'precio': precio}
                ops_dia_dict[dia] += 1

            elif bear_macro and pullback_put and vela_bajista and ema21_bear:
                pendiente = {'idx': i, 'dir': 'PUT', 'precio': precio}
                ops_dia_dict[dia] += 1

        rsi_anterior = rsi_actual

    # ============================================================
    #  RESULTADOS
    # ============================================================
    total = len(operaciones)
    if total == 0:
        print("Sin operaciones — ajustar parámetros.")
        return

    wins    = sum(1 for o in operaciones if o.win)
    losses  = total - wins
    wr      = wins / total * 100
    pnl     = capital - 100.0
    ganan   = sum(o.profit for o in operaciones if o.profit > 0)
    pierd   = abs(sum(o.profit for o in operaciones if o.profit < 0))
    pf      = ganan / pierd if pierd > 0 else float('inf')
    expect  = (wr / 100 * PAYOUT * STAKE) - ((100 - wr) / 100 * STAKE)
    dias_r  = (ts_1m[-1] - ts_1m[0]) / (1000 * 86400)
    opd     = total / dias_r if dias_r else 0

    print("=" * 60)
    print(f"RESULTADOS — SNIPER PULLBACK — {simbolo} 1m (hold={DURACION_VELAS}min)")
    print("=" * 60)
    print(f"  Total ops   : {total}")
    print(f"  Wins / Loss : {wins} / {losses}")
    print(f"  Win Rate    : {wr:.1f}%")
    print(f"  P&L total   : ${pnl:+.2f}")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Drawdown: {drawdown_max*100:.1f}%")
    print(f"  Expectativa : ${expect:.3f}/trade")
    print(f"  Ops/día     : {opd:.1f}")
    print()

    if wr >= 75:
        print("  [OK] MUY BUENO (>=75%) — Candidato para real")
    elif wr >= 65:
        print("  [>>] BUENO (65-75%) — Considerar ajustes")
    elif wr >= 55:
        print("  [~] REGULAR (55-65%) — Necesita optimizacion")
    else:
        print("  [!] BAJO (<55%) — No usar dinero real")

    # WR por dirección
    call_ops = [o for o in operaciones if o.dir == 'CALL']
    put_ops  = [o for o in operaciones if o.dir == 'PUT']
    print(f"\n  WR CALL : {sum(o.win for o in call_ops)/len(call_ops)*100:.1f}%  ({sum(o.win for o in call_ops)}W/{len(call_ops)-sum(o.win for o in call_ops)}L)" if call_ops else "  Sin CALL")
    print(f"  WR PUT  : {sum(o.win for o in put_ops)/len(put_ops)*100:.1f}%  ({sum(o.win for o in put_ops)}W/{len(put_ops)-sum(o.win for o in put_ops)}L)" if put_ops else "  Sin PUT")

    print("\n  ÚLTIMAS 12 OPS:")
    for o in operaciones[-12:]:
        fecha = datetime.fromtimestamp(ts_1m[o.idx] / 1000).strftime("%m-%d %H:%M")
        r     = "WIN " if o.win else "LOSS"
        cambio = (o.salida - o.entrada) / o.entrada * 100
        print(f"  {r} {fecha} {o.dir:4} | ${o.entrada:.2f}->${o.salida:.2f} ({cambio:+.3f}%) | {o.profit:+.2f}")


if __name__ == "__main__":
    print("\n=== SNIPER PULLBACK v2.1 — ETHUSDT 15-MIN HOLD ===")
    DURACION_VELAS = 15
    run_backtest("ETHUSDT", dias=14)

    print("\n=== SNIPER PULLBACK v2.1 — BTCUSDT 15-MIN HOLD ===")
    run_backtest("BTCUSDT", dias=14)

