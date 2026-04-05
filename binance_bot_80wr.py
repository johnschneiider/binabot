"""
BOT BINANCE - FRANCOTIRADOR v3
Estrategia multi-indicador con anti-sesgo y filtro momentum real.

LECCIONES DEL ANALISIS (51 ops, WR 41%):
  - Bot viejo usaba ema_crossover simple → 45/51 eran PUT en mercado lateral
  - Rachas de 12 loss seguidas = mercado lateral, bot seguía vendiendo
  - Fix: requiere momentum real (precio se movió en la dirección los últimos N ticks)
         + filtro de divergencia (si precio sube mientras bot quiere PUT → skip)
         + cooldown progresivo tras pérdida
         + máx 2 ops simultáneas por dirección entre todos los activos
"""

import asyncio, json, time, statistics
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
import websockets, urllib.request

# ─────────────────────────────────────────
#  CONFIG (Cargada de bot_config.json)
# ─────────────────────────────────────────
def load_config():
    try:
        with open("/var/www/intradia.com.co/bot_config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERR] cargando config: {e}", flush=True)
        return {
            "ADX_MIN": 25.0, "EMA_GAP_PCT": 0.08, "RSI_CALL_MAX": 65.0,
            "RSI_PUT_MIN": 35.0, "MOMENTUM_MIN_PCT": 0.03, "DURACION_SEG": 120,
            "STAKE": 1.0, "PAYOUT": 0.95, "MAX_OPS_DIA": 50, "COOLDOWN_BASE": 40
        }

_cfg = load_config()
DJANGO_API_URL   = "http://127.0.0.1:8001/api/binance/guardar/"
DJANGO_TICK_URL  = "http://127.0.0.1:8001/api/binance/tick/"

# DJANGO_API_URL   = "https://intradia.com.co/api/binance/guardar/"
# DJANGO_TICK_URL  = "https://intradia.com.co/api/binance/tick/"

STAKE            = _cfg.get("STAKE", 1.0)
PAYOUT           = _cfg.get("PAYOUT", 0.95)
DURACION_SEG     = _cfg.get("DURACION_SEG", 120)
COOLDOWN_BASE    = _cfg.get("COOLDOWN_BASE", 40)
WARMUP_TICKS     = 80
MAX_OPS_DIA      = _cfg.get("MAX_OPS_DIA", 50)
MAX_CALLS_ACTIVOS = 2
MAX_PUTS_ACTIVOS  = 2

ADX_MIN          = _cfg.get("ADX_MIN", 25.0)
EMA_GAP_PCT      = _cfg.get("EMA_GAP_PCT", 0.08)
RSI_CALL_MAX     = _cfg.get("RSI_CALL_MAX", 65.0)
RSI_PUT_MIN      = _cfg.get("RSI_PUT_MIN", 35.0)
MOMENTUM_MIN_PCT = _cfg.get("MOMENTUM_MIN_PCT", 0.03)
MOMENTUM_TICKS   = 15

# ─────────────────────────────────────────
#  INDICADORES
# ─────────────────────────────────────────
def ema_calc(precio, prev, periodo):
    if prev is None: return precio
    a = 2.0 / (periodo + 1.0)
    return a * precio + (1.0 - a) * prev

def rsi(precios, n=14):
    if len(precios) < n + 1: return 50.0
    cambios = [precios[i] - precios[i-1] for i in range(-n, 0)]
    g = sum(c for c in cambios if c > 0) / n
    p = sum(-c for c in cambios if c < 0) / n
    if p == 0: return 100.0
    return 100.0 - 100.0 / (1.0 + g / p)

def adx(precios, n=14):
    if len(precios) < n + 2: return 0.0
    dm_up, dm_dn, tr_list = [], [], []
    for i in range(-n, 0):
        h = max(precios[i], precios[i-1])
        l = min(precios[i], precios[i-1])
        pc = precios[i-1]
        up = h - precios[i-1]; dn = precios[i-1] - l
        dm_up.append(up if up > dn and up > 0 else 0)
        dm_dn.append(dn if dn > up and dn > 0 else 0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(tr_list) / n or 1
    dip = sum(dm_up) / n / atr * 100
    dim = sum(dm_dn) / n / atr * 100
    if dip + dim == 0: return 0.0
    return abs(dip - dim) / (dip + dim) * 100

def bollinger(precios, n=20):
    """Retorna (posicion_bb 0-1, bandwidth_pct)"""
    if len(precios) < n: return 0.5, 0.0
    arr = precios[-n:]
    med = sum(arr) / n
    std = statistics.stdev(arr) if len(arr) > 1 else 0.0
    if std == 0: return 0.5, 0.0
    sup = med + 2 * std; inf = med - 2 * std
    pos = (precios[-1] - inf) / (sup - inf)
    bw  = (sup - inf) / med * 100
    return max(0.0, min(1.0, pos)), bw

def stoch(precios, n=14):
    if len(precios) < n: return 50.0
    arr = precios[-n:]
    hi, lo = max(arr), min(arr)
    if hi == lo: return 50.0
    return (precios[-1] - lo) / (hi - lo) * 100

def momentum_pct(precios, n=15):
    """% de cambio en los últimos n ticks"""
    if len(precios) < n + 1: return 0.0
    base = precios[-n-1]
    if base == 0: return 0.0
    return (precios[-1] - base) / base * 100

def ema_slope(precios, ema_val, n=5):
    """Pendiente de la EMA: positiva=subiendo, negativa=bajando"""
    if len(precios) < n + 1 or ema_val is None: return 0.0
    # Aproximamos slope calculando EMA hace n ticks
    e = None
    for p in precios[-(n+10):-(n)]:
        e = ema_calc(p, e, 5)
    if e is None or e == 0: return 0.0
    return (ema_val - e) / e * 100

# ─────────────────────────────────────────
#  ESTADO
# ─────────────────────────────────────────
def save_bot_status(status_text):
    try:
        with open("/tmp/bot_binance_status.json", "w") as f:
            json.dump({"status": status_text, "timestamp": time.time()}, f)
    except:
        pass

@dataclass
class Activo:
    sym: str
    precios: list = field(default_factory=list)
    e5:  Optional[float] = None
    e21: Optional[float] = None
    e55: Optional[float] = None
    e200: Optional[float] = None
    cooldown: int = 0
    cooldown_mult: float = 1.0   # se duplica tras pérdida, vuelve a 1 tras win
    pendiente: Optional[object] = None
    ops_hoy: int = 0
    wins: int = 0
    losses: int = 0
    total: int = 0
    tick: int = 0

@dataclass
class Op:
    sym: str
    dir: str
    entrada: float
    t_inicio: float
    razon: str
    num: int

# Estado global de dirección (anti-sesgo)
ops_abiertas_call = 0
ops_abiertas_put  = 0

# ─────────────────────────────────────────
#  ESTRATEGIA FRANCOTIRADOR v3
# ─────────────────────────────────────────
def evaluar(activo: Activo, precio: float):
    activo.precios.append(precio)
    if len(activo.precios) > 500:
        activo.precios = activo.precios[-500:]

    if activo.cooldown > 0:
        activo.cooldown -= 1
        return "NEUTRAL", "cd"

    if len(activo.precios) < WARMUP_TICKS:
        return "NEUTRAL", f"warmup_{len(activo.precios)}"

    # Actualizar EMAs
    activo.e5   = ema_calc(precio, activo.e5,   5)
    activo.e21  = ema_calc(precio, activo.e21,  21)
    activo.e55  = ema_calc(precio, activo.e55,  55)
    activo.e200 = ema_calc(precio, activo.e200, 200)

    rsi_val    = rsi(activo.precios)
    adx_val    = adx(activo.precios)
    bb_pos, bw = bollinger(activo.precios)
    stoch_val  = stoch(activo.precios)
    mom        = momentum_pct(activo.precios, MOMENTUM_TICKS)
    slope_e5   = ema_slope(activo.precios, activo.e5)

    gap = abs(activo.e5 - activo.e55) / activo.e55 * 100 if activo.e55 else 0

    # ── FILTROS OBLIGATORIOS (cualquier dirección) ──
    if adx_val < ADX_MIN:
        return "NEUTRAL", f"adx_bajo_{adx_val:.1f}"
    if gap < EMA_GAP_PCT:
        return "NEUTRAL", f"gap_bajo_{gap:.3f}"
    if bw < 0.15:
        return "NEUTRAL", f"squeeze_bw_{bw:.2f}"  # mercado comprimido, esperar breakout

    # ── FILTRO ANTI-SESGO: límite de ops abiertas por dirección ──
    global ops_abiertas_call, ops_abiertas_put

    # ── SEÑAL CALL ──
    call_ok = (
        activo.e5  > activo.e21             # EMA corta > media
        and activo.e21 > activo.e55          # EMA media > lenta
        and precio   > activo.e200           # precio sobre EMA200 (tendencia macro)
        and rsi_val  < RSI_CALL_MAX          # RSI no sobrecomprado
        and bb_pos   < 0.80                  # BB no en techo
        and stoch_val < 80                   # Stoch no sobrecomprado
        and mom      > MOMENTUM_MIN_PCT      # momentum alcista real
        and slope_e5 > 0                     # EMA5 tiene pendiente positiva
    )

    # ── SEÑAL PUT ──
    put_ok = (
        activo.e5  < activo.e21             # EMA corta < media
        and activo.e21 < activo.e55          # EMA media < lenta
        and precio   < activo.e200           # precio bajo EMA200 (tendencia macro)
        and rsi_val  > RSI_PUT_MIN           # RSI no sobrevendido
        and bb_pos   > 0.20                  # BB no en suelo
        and stoch_val > 20                   # Stoch no sobrevendido
        and mom      < -MOMENTUM_MIN_PCT     # momentum bajista real
        and slope_e5 < 0                     # EMA5 tiene pendiente negativa
    )

    if call_ok and ops_abiertas_call < MAX_CALLS_ACTIVOS:
        cd = int(COOLDOWN_BASE * activo.cooldown_mult)
        activo.cooldown = cd
        razon = f"call_adx{adx_val:.0f}_rsi{rsi_val:.0f}_mom{mom:.2f}_bb{bb_pos:.2f}"
        return "CALL", razon

    if put_ok and ops_abiertas_put < MAX_PUTS_ACTIVOS:
        cd = int(COOLDOWN_BASE * activo.cooldown_mult)
        activo.cooldown = cd
        razon = f"put_adx{adx_val:.0f}_rsi{rsi_val:.0f}_mom{mom:.2f}_bb{bb_pos:.2f}"
        return "PUT", razon

    return "NEUTRAL", "sin_conf"

# ─────────────────────────────────────────
#  HTTP
# ─────────────────────────────────────────
def guardar_operacion(op: Op, precio_salida, es_win, profit):
    data = {
        "simbolo": op.sym,
        "direccion": op.dir,
        "precio_entrada": op.entrada,
        "razon": op.razon,
        "confianza": "alta",
        "es_win": es_win,
        "profit": profit,
    }
    try:
        req = urllib.request.Request(
            DJANGO_API_URL,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json", "Host": "www.vitalmix.com.co"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[WARN] guardar: {e}", flush=True)

def guardar_tick(sym, precio):
    try:
        req = urllib.request.Request(
            DJANGO_TICK_URL,
            data=json.dumps({"simbolo": sym, "precio": precio}).encode(),
            headers={"Content-Type": "application/json", "Host": "www.vitalmix.com.co"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
    except:
        pass

# ─────────────────────────────────────────
#  CERRAR OPERACIÓN
# ─────────────────────────────────────────
def cerrar(activo: Activo, op: Op, precio, hora):
    global ops_abiertas_call, ops_abiertas_put

    es_win = (precio > op.entrada) if op.dir == "CALL" else (precio < op.entrada)
    profit = STAKE * PAYOUT if es_win else -STAKE

    activo.total  += 1
    if es_win:
        activo.wins += 1
        activo.cooldown_mult = max(1.0, activo.cooldown_mult / 2)  # recover
    else:
        activo.losses += 1
        activo.cooldown_mult = min(8.0, activo.cooldown_mult * 2)  # penaliza

    if op.dir == "CALL": ops_abiertas_call = max(0, ops_abiertas_call - 1)
    else:                ops_abiertas_put  = max(0, ops_abiertas_put  - 1)

    wr = activo.wins / activo.total * 100
    result = "✅ WIN" if es_win else "❌ LOSS"
    cambio = (precio - op.entrada) / op.entrada * 100
    mult_txt = f" cd_mult:{activo.cooldown_mult:.0f}x" if activo.cooldown_mult > 1 else ""
    print(
        f"[{hora}] {op.sym} {op.dir} {result} | "
        f"{op.entrada:.4f}→{precio:.4f} ({cambio:+.3f}%) | "
        f"profit:{profit:+.2f} | WR:{wr:.1f}% ({activo.wins}/{activo.total}){mult_txt}",
        flush=True
    )
    guardar_operacion(op, precio, es_win, profit)
    activo.pendiente = None

# ─────────────────────────────────────────
#  WEBSOCKET
# ─────────────────────────────────────────
async def run(simbolos):
    global ops_abiertas_call, ops_abiertas_put
    streams = "/".join(f"{s.lower()}usdt@trade" for s in simbolos)
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"
    activos = {s: Activo(sym=s) for s in simbolos}
    num = 0; ops_dia = 0; dia = datetime.now().day

    print("=" * 65, flush=True)
    print("  🎯 FRANCOTIRADOR v3 — EMA+RSI+ADX+BB+Stoch+Mom+Slope", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  ADX≥{ADX_MIN} | GAP≥{EMA_GAP_PCT}% | MOM≥{MOMENTUM_MIN_PCT}%", flush=True)
    print(f"  MaxCALL:{MAX_CALLS_ACTIVOS} | MaxPUT:{MAX_PUTS_ACTIVOS} | CD:{COOLDOWN_BASE}t", flush=True)
    print("=" * 65, flush=True)

    # Estado global de diagnósticos (para el Dashboard)
    diagnosticos = {}

    async with websockets.connect(url, ping_interval=30, ping_timeout=30) as ws:
        print("[🚀] Conectado a Binance", flush=True)
        async for msg in ws:
            try:
                raw = json.loads(msg)
                if "data" not in raw: continue
                t   = raw["data"]
                sym = t["s"].replace("USDT", "")
                precio = float(t["p"])
                hora   = datetime.fromtimestamp(t["T"]/1000, tz=timezone.utc).strftime("%H:%M:%S")

                if sym not in activos: continue
                act = activos[sym]
                act.tick += 1

                # Reset diario
                if datetime.now().day != dia:
                    dia = datetime.now().day; ops_dia = 0
                    ops_abiertas_call = 0; ops_abiertas_put = 0
                    for a in activos.values():
                        a.ops_hoy = 0
                    print(f"[{hora}] 🌅 Nuevo día", flush=True)

                # Tick a Django cada 20
                if act.tick % 20 == 0:
                    guardar_tick(sym, precio)

                # Cerrar op pendiente si venció
                if act.pendiente:
                    if time.time() - act.pendiente.t_inicio >= DURACION_SEG:
                        cerrar(act, act.pendiente, precio, hora)

                # Nueva señal
                if act.pendiente is None and ops_dia < MAX_OPS_DIA:
                    decision, razon = evaluar(act, precio)
                    if decision != "NEUTRAL":
                        num += 1; ops_dia += 1; act.ops_hoy += 1
                        if decision == "CALL": ops_abiertas_call += 1
                        else:                  ops_abiertas_put  += 1
                        act.pendiente = Op(
                            sym=sym, dir=decision, entrada=precio,
                            t_inicio=time.time(), razon=razon, num=num
                        )
                        print(
                            f"[{hora}] 🎯 #{num} {sym} {decision} @ {precio:.4f} | {razon}",
                            flush=True
                        )
                        diagnosticos[sym] = f"OPERANDO: {decision}"
                    else:
                        diagnosticos[sym] = razon
                        if act.tick % 50 == 0:
                            # Debug periódico para saber por qué no entra
                            print(f"[{hora}] {sym} scan: {razon}", flush=True)

                # Guardar resumen de diagnóstico para el Dashboard (cada 2 segs)
                if act.tick % 20 == 0:
                    status_msg = " | ".join(f"{s}: {m}" for s, m in sorted(diagnosticos.items()))
                    save_bot_status(status_msg or "Escaneando mercado...")

            except Exception as e:
                print(f"[ERR] {e}", flush=True)

async def main():
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    while True:
        try:
            await run(simbolos)
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[DESCONECTADO] {e} — retry 5s", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERROR] {e} — retry 10s", flush=True)
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
