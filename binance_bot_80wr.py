"""
BOT BINANCE - FRANCOTIRADOR v4 — MOMENTUM SNIPER 80% WR
Estrategia de momentum con cierre temprano (early take-profit).

DISEÑO PARA 80% WR:
  - Entrar SOLO con momentum fuerte confirmado en múltiples ventanas
  - Cerrar INMEDIATAMENTE cuando hay profit (early take-profit = WIN garantizado)
  - Filtro de consistencia de ticks (70%+ en la misma dirección)
  - Aceleración del momentum (velocidad creciente, no decreciente)
  - Foco en BTC/ETH (mayor liquidez, menor ruido)
  - Sin EMAs lentas ni indicadores macro para timeframe micro
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
            "ADX_MIN": 22.0, "EMA_GAP_PCT": 0.06, "RSI_CALL_MAX": 58.0,
            "RSI_PUT_MIN": 42.0, "MOMENTUM_MIN_PCT": 0.04, "DURACION_SEG": 60,
            "STAKE": 1.0, "PAYOUT": 0.95, "MAX_OPS_DIA": 50, "COOLDOWN_BASE": 25,
            "TAKE_PROFIT_PCT": 0.020, "STOP_LOSS_PCT": 0.12,
            "MIN_HOLD_SECONDS": 3, "TICK_CONSISTENCY_MIN": 0.70,
            "MOMENTUM_ACCEL_MIN": 0.002
        }

_cfg = load_config()
DJANGO_API_URL   = "http://127.0.0.1:8001/api/binance/guardar/"
DJANGO_TICK_URL  = "http://127.0.0.1:8001/api/binance/tick/"

# DJANGO_API_URL   = "https://intradia.com.co/api/binance/guardar/"
# DJANGO_TICK_URL  = "https://intradia.com.co/api/binance/tick/"

STAKE            = _cfg.get("STAKE", 1.0)
PAYOUT           = _cfg.get("PAYOUT", 0.95)
DURACION_SEG     = _cfg.get("DURACION_SEG", 60)
COOLDOWN_BASE    = _cfg.get("COOLDOWN_BASE", 25)
WARMUP_TICKS     = 60
MAX_OPS_DIA      = _cfg.get("MAX_OPS_DIA", 50)
MAX_CALLS_ACTIVOS = 2
MAX_PUTS_ACTIVOS  = 2

ADX_MIN          = _cfg.get("ADX_MIN", 22.0)
EMA_GAP_PCT      = _cfg.get("EMA_GAP_PCT", 0.06)
RSI_CALL_MAX     = _cfg.get("RSI_CALL_MAX", 58.0)
RSI_PUT_MIN      = _cfg.get("RSI_PUT_MIN", 42.0)
MOMENTUM_MIN_PCT = _cfg.get("MOMENTUM_MIN_PCT", 0.04)
MOMENTUM_TICKS   = 15

# ── EARLY EXIT (clave para 80% WR) ──
TAKE_PROFIT_PCT  = _cfg.get("TAKE_PROFIT_PCT", 0.020)   # Cerrar con +0.020% profit = WIN
STOP_LOSS_PCT    = _cfg.get("STOP_LOSS_PCT", 0.12)      # Cerrar con -0.12% = LOSS (cortar rápido)
MIN_HOLD_SECONDS = _cfg.get("MIN_HOLD_SECONDS", 3)      # Esperar mínimo 3s antes de cerrar

# ── FILTROS DE CONSISTENCIA ──
TICK_CONSISTENCY_MIN  = _cfg.get("TICK_CONSISTENCY_MIN", 0.70)  # 70%+ ticks en misma dirección
MOMENTUM_ACCEL_MIN    = _cfg.get("MOMENTUM_ACCEL_MIN", 0.002)  # Momentum acelerando

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

def momentum_pct(precios, n=15):
    """% de cambio en los últimos n ticks"""
    if len(precios) < n + 1: return 0.0
    base = precios[-n-1]
    if base == 0: return 0.0
    return (precios[-1] - base) / base * 100

def tick_consistency(precios, n=20):
    """% de ticks consecutivos en la misma dirección.
    Retorna (pct_up, pct_down) — cuántos ticks subieron vs bajaron."""
    if len(precios) < n + 1: return 0.5, 0.5
    cambios = [precios[i] - precios[i-1] for i in range(-n, 0)]
    up   = sum(1 for c in cambios if c > 0)
    down = sum(1 for c in cambios if c < 0)
    total = up + down
    if total == 0: return 0.5, 0.5
    return up / total, down / total

def momentum_acceleration(precios, n_recent=5, n_prev=5):
    """Compara momentum reciente vs previo. Positivo = acelerando hacia arriba."""
    if len(precios) < n_recent + n_prev + 1: return 0.0
    mom_recent = momentum_pct(precios, n_recent)
    # Momentum del bloque previo
    prev_slice = precios[:-(n_recent)]
    mom_prev = momentum_pct(prev_slice, n_prev) if len(prev_slice) > n_prev else 0.0
    return mom_recent - mom_prev

def max_drawdown_recent(precios, n=20):
    """Max drawdown (caída desde máximo) en los últimos n ticks, en %."""
    if len(precios) < n: return 0.0
    arr = precios[-n:]
    peak = arr[0]
    max_dd = 0.0
    for p in arr:
        if p > peak: peak = p
        dd = (peak - p) / peak * 100
        if dd > max_dd: max_dd = dd
    return max_dd

def max_runup_recent(precios, n=20):
    """Max run-up (subida desde mínimo) en los últimos n ticks, en %."""
    if len(precios) < n: return 0.0
    arr = precios[-n:]
    trough = arr[0]
    max_ru = 0.0
    for p in arr:
        if p < trough: trough = p
        if trough > 0:
            ru = (p - trough) / trough * 100
            if ru > max_ru: max_ru = ru
    return max_ru

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
    e13: Optional[float] = None
    e21: Optional[float] = None
    cooldown: int = 0
    cooldown_mult: float = 1.0
    pendiente: Optional[object] = None
    ops_hoy: int = 0
    wins: int = 0
    losses: int = 0
    total: int = 0
    tick: int = 0
    win_streak: int = 0
    loss_streak: int = 0

@dataclass
class Op:
    sym: str
    dir: str
    entrada: float
    t_inicio: float
    razon: str
    num: int
    max_favorable: float = 0.0  # Track max favorable price movement

# Estado global de dirección (anti-sesgo)
ops_abiertas_call = 0
ops_abiertas_put  = 0

# ─────────────────────────────────────────
#  ESTRATEGIA FRANCOTIRADOR v4 — MOMENTUM SNIPER
# ─────────────────────────────────────────
def evaluar(activo: Activo, precio: float):
    activo.precios.append(precio)
    if len(activo.precios) > 500:
        activo.precios = activo.precios[-500:]

    # Actualizar EMAs siempre (incluso en cooldown)
    activo.e5   = ema_calc(precio, activo.e5,    5)
    activo.e13  = ema_calc(precio, activo.e13,  13)
    activo.e21  = ema_calc(precio, activo.e21,  21)

    if activo.cooldown > 0:
        activo.cooldown -= 1
        return "NEUTRAL", "cd"

    if len(activo.precios) < WARMUP_TICKS:
        return "NEUTRAL", f"warmup_{len(activo.precios)}"

    # ── INDICADORES ──
    rsi_val    = rsi(activo.precios)
    adx_val    = adx(activo.precios)

    # Momentum en múltiples ventanas
    mom5       = momentum_pct(activo.precios, 5)
    mom10      = momentum_pct(activo.precios, 10)
    mom20      = momentum_pct(activo.precios, 20)

    # Consistencia de ticks (% de ticks up vs down)
    pct_up, pct_down = tick_consistency(activo.precios, 20)

    # Aceleración del momentum
    accel      = momentum_acceleration(activo.precios, 5, 5)

    gap = abs(activo.e5 - activo.e21) / activo.e21 * 100 if activo.e21 else 0

    # ── FILTROS OBLIGATORIOS ──
    if adx_val < ADX_MIN:
        return "NEUTRAL", f"adx_bajo_{adx_val:.1f}"
    if gap < EMA_GAP_PCT:
        return "NEUTRAL", f"gap_bajo_{gap:.3f}"

    # ── FILTRO ANTI-SESGO ──
    global ops_abiertas_call, ops_abiertas_put

    # ── SEÑAL CALL — Momentum alcista confirmado ──
    call_ok = (
        activo.e5 > activo.e13 > activo.e21    # EMAs alineadas al alza
        and rsi_val < RSI_CALL_MAX              # RSI no sobrecomprado
        and rsi_val > 35                        # No en zona de sobreventa (evitar rebote muerto)
        and mom5 > MOMENTUM_MIN_PCT             # Momentum 5-tick positivo
        and mom10 > 0                           # Momentum 10-tick positivo
        and mom20 > 0                           # Momentum 20-tick positivo (tendencia)
        and pct_up >= TICK_CONSISTENCY_MIN       # 65%+ de ticks subiendo
        and accel > MOMENTUM_ACCEL_MIN          # Momentum acelerando
        and max_drawdown_recent(activo.precios, 15) < 0.08  # Sin caídas fuertes recientes
    )

    # ── SEÑAL PUT — Momentum bajista confirmado ──
    put_ok = (
        activo.e5 < activo.e13 < activo.e21    # EMAs alineadas a la baja
        and rsi_val > RSI_PUT_MIN               # RSI no sobrevendido
        and rsi_val < 65                        # No en zona de sobrecompra (evitar corrección)
        and mom5 < -MOMENTUM_MIN_PCT            # Momentum 5-tick negativo
        and mom10 < 0                           # Momentum 10-tick negativo
        and mom20 < 0                           # Momentum 20-tick negativo (tendencia)
        and pct_down >= TICK_CONSISTENCY_MIN     # 65%+ de ticks bajando
        and accel < -MOMENTUM_ACCEL_MIN         # Momentum acelerando a la baja
        and max_runup_recent(activo.precios, 15) < 0.08  # Sin subidas fuertes recientes
    )

    if call_ok and ops_abiertas_call < MAX_CALLS_ACTIVOS:
        cd = int(COOLDOWN_BASE * activo.cooldown_mult)
        activo.cooldown = cd
        razon = f"call_adx{adx_val:.0f}_rsi{rsi_val:.0f}_mom{mom5:.3f}_tc{pct_up:.0%}_acc{accel:.3f}"
        return "CALL", razon

    if put_ok and ops_abiertas_put < MAX_PUTS_ACTIVOS:
        cd = int(COOLDOWN_BASE * activo.cooldown_mult)
        activo.cooldown = cd
        razon = f"put_adx{adx_val:.0f}_rsi{rsi_val:.0f}_mom{mom5:.3f}_tc{pct_down:.0%}_acc{accel:.3f}"
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
def cerrar(activo: Activo, op: Op, precio, hora, motivo_cierre="expiry"):
    global ops_abiertas_call, ops_abiertas_put

    es_win = (precio > op.entrada) if op.dir == "CALL" else (precio < op.entrada)
    profit = STAKE * PAYOUT if es_win else -STAKE

    activo.total  += 1
    if es_win:
        activo.wins += 1
        activo.win_streak += 1
        activo.loss_streak = 0
        activo.cooldown_mult = max(1.0, activo.cooldown_mult / 2)  # recover
    else:
        activo.losses += 1
        activo.loss_streak += 1
        activo.win_streak = 0
        activo.cooldown_mult = min(8.0, activo.cooldown_mult * 2)  # penaliza

    if op.dir == "CALL": ops_abiertas_call = max(0, ops_abiertas_call - 1)
    else:                ops_abiertas_put  = max(0, ops_abiertas_put  - 1)

    wr = activo.wins / activo.total * 100
    result = "✅ WIN" if es_win else "❌ LOSS"
    cambio = (precio - op.entrada) / op.entrada * 100
    elapsed = time.time() - op.t_inicio
    mult_txt = f" cd_mult:{activo.cooldown_mult:.0f}x" if activo.cooldown_mult > 1 else ""
    print(
        f"[{hora}] {op.sym} {op.dir} {result} ({motivo_cierre} {elapsed:.0f}s) | "
        f"{op.entrada:.4f}→{precio:.4f} ({cambio:+.3f}%) | "
        f"profit:{profit:+.2f} | WR:{wr:.1f}% ({activo.wins}/{activo.total}){mult_txt}",
        flush=True
    )
    guardar_operacion(op, precio, es_win, profit)
    activo.pendiente = None

def check_early_exit(activo: Activo, op: Op, precio, hora):
    """Revisa si debemos cerrar la operación antes de tiempo.
    CLAVE PARA 80% WR: cerrar en cuanto hay profit."""
    elapsed = time.time() - op.t_inicio

    # No cerrar antes del tiempo mínimo de hold
    if elapsed < MIN_HOLD_SECONDS:
        return False

    # Calcular P&L actual en %
    if op.dir == "CALL":
        pnl_pct = (precio - op.entrada) / op.entrada * 100
    else:
        pnl_pct = (op.entrada - precio) / op.entrada * 100

    # Track max favorable
    if pnl_pct > op.max_favorable:
        op.max_favorable = pnl_pct

    # ── EARLY TAKE PROFIT ── (cerrar en cuanto hay profit suficiente)
    if pnl_pct >= TAKE_PROFIT_PCT:
        cerrar(activo, op, precio, hora, motivo_cierre="TP")
        return True

    # ── EARLY STOP LOSS ── (cortar pérdidas rápido)
    if pnl_pct <= -STOP_LOSS_PCT and elapsed >= 15:
        cerrar(activo, op, precio, hora, motivo_cierre="SL")
        return True

    # ── TRAILING STOP ── (si fue favorable y volvió a 0, cerrar)
    if op.max_favorable >= TAKE_PROFIT_PCT * 2 and pnl_pct <= TAKE_PROFIT_PCT * 0.3:
        cerrar(activo, op, precio, hora, motivo_cierre="trail")
        return True

    # ── EXPIRACIÓN NORMAL ──
    if elapsed >= DURACION_SEG:
        cerrar(activo, op, precio, hora, motivo_cierre="expiry")
        return True

    return False

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
    print("  🎯 FRANCOTIRADOR v4 — MOMENTUM SNIPER 80% WR", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  ADX≥{ADX_MIN} | GAP≥{EMA_GAP_PCT}% | MOM≥{MOMENTUM_MIN_PCT}%", flush=True)
    print(f"  TP:{TAKE_PROFIT_PCT}% | SL:{STOP_LOSS_PCT}% | Hold:{DURACION_SEG}s", flush=True)
    print(f"  TickConsistency≥{TICK_CONSISTENCY_MIN:.0%} | Accel≥{MOMENTUM_ACCEL_MIN}", flush=True)
    print(f"  MaxCALL:{MAX_CALLS_ACTIVOS} | MaxPUT:{MAX_PUTS_ACTIVOS} | CD:{COOLDOWN_BASE}t", flush=True)
    print("=" * 65, flush=True)

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

                # ── EARLY EXIT: revisar cada tick si hay que cerrar ──
                if act.pendiente:
                    check_early_exit(act, act.pendiente, precio, hora)

                # Nueva señal (solo si no hay op pendiente)
                if act.pendiente is None and ops_dia < MAX_OPS_DIA:
                    decision, razon = evaluar(act, precio)
                    if decision != "NEUTRAL":
                        # Filtro extra: si venimos de racha perdedora, ser más exigente
                        if act.loss_streak >= 3:
                            mom5 = momentum_pct(act.precios, 5)
                            if abs(mom5) < MOMENTUM_MIN_PCT * 2:
                                diagnosticos[sym] = f"loss_streak_{act.loss_streak}_skip"
                                continue

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
                            print(f"[{hora}] {sym} scan: {razon}", flush=True)

                # Guardar resumen de diagnóstico para el Dashboard
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
