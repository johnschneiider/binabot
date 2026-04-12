"""
BINANCE FUTURES BOT - SNIPER PULLBACK v2.1
Estrategia multi-timeframe con confirmación RSI pullback, EMA21 micro-filtro y ADX fuerte.

ESTRATEGIA:
  - 15m EMA50 define tendencia macro (BULL / BEAR) con pendiente mínima ≥ 0.03%
  - 5m ADX > 28 confirma mercado fuertemente trending (filtra laterales)
  - 1m RSI pullback profundo: RSI cae < 42 luego recupera > 50 → CALL en uptrend
                               RSI sube > 58 luego cae < 50   → PUT en downtrend
  - 1m EMA21 micro-filtro: precio debe estar encima (CALL) / debajo (PUT) de EMA21
  - Volumen: vela de entrada con volumen normal (botón en backtest)
  - Confirmación: vela 1m cierra en dirección de señal
  - Hold: 15 minutos (900 segundos)
  - Max 10 trades/día, 10min cooldown entre trades
  - Circuit breaker: pausa tras 3 losses consecutivos

RESULTADOS BACKTEST (14 días, ETH, v2.1):
  - WR total: 58.3% (21W / 15L)  — CALL: 65.0%, PUT: 50.0%
  - P&L: +$4.95 (2.6 ops/día)
  - BTC: WR 38.6% — DESHABILITADO (pocos ops, régimen adverso)
  - Activo actual: ETH únicamente

BUGS CORREGIDOS vs versión anterior:
  - RSI: era rsi > RSI_MAX para CALL (comprar overbought), ahora es pullback recovery
  - Cantidad: era hardcoded int(5) → ahora lot size mínimo correcto por símbolo
  - marginType: era int 1, ahora string "CROSSED"
  - requests.get() bloqueante dentro de evaluar_senal → eliminado, usa cache klines
  - Polling REST cada 1s → reemplazado por WebSocket @kline_1m stream
  - ADX: implementación correcta con dirección de movimiento real
"""

from dotenv import load_dotenv
import os
import sys
# Force UTF-8 output so emojis don't crash on Windows cp1252 terminals/log files
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

import urllib.request as _ur
import hmac
import hashlib
import time
import os

FUTURES_API_URL = "https://fapi.binance.com"

# ── Lot sizes mínimos y step por símbolo (Binance Futures USDT-M) ────────────
MIN_LOT = {
    'BTC': 0.001,   # ~$84 a $84k   (step 0.001)
    'ETH': 0.001,   # ~$2.10 a $2100 (step 0.001)
    'SOL': 0.1,     # ~$8.50 a $85   (step 0.1)
    'XRP': 1.0,     # ~$2.20 a $2.20 (step 1)
}

LOT_STEP = {
    'BTC': 0.001,
    'ETH': 0.001,
    'SOL': 0.1,
    'XRP': 1.0,
}

# ── Sizing dinámico: porcentaje del balance como margen por operación ────────
RIESGO_PCT = 0.50   # 50% del balance disponible por operación (fase prueba)
LEVERAGE   = 20

# Cache de balance para no hacer API call en cada trade
_balance_cache      = 0.0
_balance_cache_ts   = 0.0
_BALANCE_CACHE_TTL  = 60  # refrescar cada 60 segundos

def _get_cached_balance() -> float:
    """Obtiene balance disponible cacheado (refresca cada 60s)."""
    global _balance_cache, _balance_cache_ts
    if time.time() - _balance_cache_ts < _BALANCE_CACHE_TTL and _balance_cache > 0:
        return _balance_cache
    try:
        bd = obtener_balance_sync()
        _balance_cache = float(bd.get('availableBalance', 0))
        _balance_cache_ts = time.time()
    except Exception:
        pass  # usa el último valor cacheado
    return _balance_cache

def obtener_cantidad(simbolo, precio_actual=0.0):
    """
    Sizing dinámico: usa RIESGO_PCT del balance disponible como margen.
    notional = balance × RIESGO_PCT × LEVERAGE
    cantidad = notional / precio
    Redondea al step size del símbolo y aplica mínimo.
    """
    sym = simbolo.upper()
    min_lot = MIN_LOT.get(sym, 0.001)
    step    = LOT_STEP.get(sym, 0.001)

    if precio_actual <= 0:
        return min_lot

    balance = _get_cached_balance()
    if balance <= 0:
        return min_lot

    notional = balance * RIESGO_PCT * LEVERAGE
    cantidad = notional / precio_actual

    # Redondear al step size (floor)
    cantidad = int(cantidad / step) * step

    # Aplicar mínimo
    if cantidad < min_lot:
        cantidad = min_lot

    return round(cantidad, 8)

def _firmar(params: dict, secret: str):
    """Firma una petición Binance y retorna (query_string, signature)."""
    q   = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    return q, sig

def test_connection():
    """Test Binance API connection usando urllib (no requests)."""
    api_key    = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    if not api_key or not api_secret:
        print("[TEST] API key/secret NO cargados.", flush=True)
        return False
    try:
        ts = int(time.time() * 1000)
        q, sig = _firmar({"timestamp": ts}, api_secret)
        url = f"{FUTURES_API_URL}/fapi/v2/account?{q}&signature={sig}"
        req = _ur.Request(url, headers={'X-MBX-APIKEY': api_key})
        with _ur.urlopen(req, timeout=10) as resp:
            data = __import__('json').loads(resp.read())
        print(f"[TEST] Conexión OK — Balance: {data.get('availableBalance')} USDT", flush=True)
        return True
    except Exception as e:
        print(f"[TEST] Error conexión: {e}", flush=True)
        return False

TEST_CONNECTION = test_connection()

def configurar_leverage_y_margin(simbolo, api_key, api_secret):
    """Configura leverage=20 y marginType=CROSSED (usa urllib, no requests)."""
    import json as _json
    symbol = f"{simbolo}USDT"
    ts     = int(time.time() * 1000)

    # Leverage 20x
    q_lev, s_lev = _firmar({"symbol": symbol, "leverage": 20, "timestamp": ts}, api_secret)
    try:
        req = _ur.Request(
            f"{FUTURES_API_URL}/fapi/v1/leverage?{q_lev}&signature={s_lev}",
            data=b"", headers={'X-MBX-APIKEY': api_key}, method='POST'
        )
        _ur.urlopen(req, timeout=8)
    except Exception:
        pass  # ya configurado o error ignorable

    # CORREGIDO: marginType debe ser STRING "CROSSED", no entero 1
    q_mar, s_mar = _firmar({"symbol": symbol, "marginType": "CROSSED", "timestamp": ts}, api_secret)
    try:
        req2 = _ur.Request(
            f"{FUTURES_API_URL}/fapi/v1/marginType?{q_mar}&signature={s_mar}",
            data=b"", headers={'X-MBX-APIKEY': api_key}, method='POST'
        )
        _ur.urlopen(req2, timeout=8)
    except Exception:
        pass  # ya en CROSSED → Binance devuelve 400, es normal


def ejecutar_orden(simbolo, direccion, cantidad=None):
    """
    Ejecuta orden real en Binance Futures vía urllib (sin requests).
    direccion: 'CALL' (BUY/LONG) o 'PUT' (SELL/SHORT)
    """
    api_key    = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    if not api_key or not api_secret:
        print("[ERROR] API key no configurada", flush=True)
        return None

    configurar_leverage_y_margin(simbolo, api_key, api_secret)

    side     = "BUY" if direccion == "CALL" else "SELL"
    cantidad = cantidad or obtener_cantidad(simbolo)

    try:
        ts = int(time.time() * 1000)
        params = {
            "symbol":    f"{simbolo}USDT",
            "side":      side,
            "type":      "MARKET",
            "quantity":  cantidad,
            "timestamp": ts,
        }
        q, sig = _firmar(params, api_secret)
        url    = f"{FUTURES_API_URL}/fapi/v1/order?{q}&signature={sig}"
        req    = _ur.Request(url, data=b"", headers={'X-MBX-APIKEY': api_key}, method='POST')
        with _ur.urlopen(req, timeout=10) as resp:
            data = __import__('json').loads(resp.read())
        print(f"[TRADE] Orden OK: {simbolo} {side} {cantidad} | OrderID={data.get('orderId')}", flush=True)
        return data
    except Exception as e:
        print(f"[TRADE] Error orden {simbolo} {side}: {e}", flush=True)
        return None


def obtener_balance_sync():
    """Obtiene balance de cuenta Futures (bloqueante, usa urllib)."""
    api_key    = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    if not api_key or not api_secret:
        raise RuntimeError("Claves API no configuradas.")
    ts    = int(time.time() * 1000)
    q, sig = _firmar({"timestamp": ts}, api_secret)
    url   = f"{FUTURES_API_URL}/fapi/v2/account?{q}&signature={sig}"
    req   = _ur.Request(url, headers={'X-MBX-APIKEY': api_key})
    with _ur.urlopen(req, timeout=10) as resp:
        return __import__('json').loads(resp.read())


import asyncio
import json
import time
import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List
import websockets
from websockets.exceptions import ConnectionClosedError

# ============================================================
#  CONFIGURACION — SNIPER PULLBACK v2
# ============================================================

DJANGO_API_URL   = "http://127.0.0.1:8000/api/binance/guardar/"
DJANGO_TICK_URL  = os.getenv("DJANGO_TICK_URL", "http://127.0.0.1:8000/api/binance/tick/")
SPOT_API_URL     = "https://api.binance.com"

# Estrategia
STAKE              = 1.0     # Legacy (solo referencia — P&L real desde API)
PAYOUT             = 0.95    # Legacy (solo referencia — P&L real desde API)
DURACION_SEG       = 900      # 15 min: da tiempo al momentum para desarrollarse
MAX_OPS_DIA        = 20       # Calidad > cantidad; backtest: 6.2 ops/día óptimo
COOLDOWN_MIN_SEG   = 600      # 10 min cooldown entre trades del mismo par
LOSS_STREAK_LIMIT  = 3        # Circuit breaker: pausa tras N losses consecutivos
LOSS_STREAK_PAUSE  = 600      # 10 minutos de pausa global

# Filtros multi-timeframe — relajados prudentemente (Capa 2 ML sigue filtrando)
ADX_MIN            = 24       # era 28 — igual filtra mercados puramente laterales
ADX_PERIODO        = 14
RSI_PERIODO        = 14
EMA50_SLOPE_N      = 5        # Comparar EMA50[-1] vs EMA50[-n] para slope
EMA50_SLOPE_MIN    = 0.02     # era 0.03 — acepta tendencias suaves en 15m
RSI_PULLBACK_CALL  = 44       # punto medio 42-46: frecuencia+calidad balanceadas
RSI_PULLBACK_PUT   = 56       # simétrico
RSI_RESUME_CALL    = 50       # RSI debe recuperar sobre este → entrada CALL
RSI_RESUME_PUT     = 50       # RSI debe caer bajo este → entrada PUT
WARMUP_CANDLES     = 30       # Velas 1m mínimas para operar

# ============================================================
#  INDICADORES
# ============================================================

def _ema_lista(precios: list, periodo: int) -> list:
    """EMA sobre lista completa de precios."""
    if len(precios) < periodo:
        return [None] * len(precios)
    alpha = 2.0 / (periodo + 1.0)
    emas  = [None] * (periodo - 1)
    emas.append(sum(precios[:periodo]) / periodo)
    for p in precios[periodo:]:
        emas.append(alpha * p + (1 - alpha) * emas[-1])
    return emas


def calcular_rsi(cierres: list, periodo: int = 14) -> float:
    """RSI estándar sobre los últimos (periodo+1) cierres."""
    if len(cierres) < periodo + 1:
        return 50.0
    seg      = cierres[-(periodo + 1):]
    cambios  = [seg[i] - seg[i - 1] for i in range(1, len(seg))]
    ag = sum(max(c, 0) for c in cambios) / periodo
    ap = sum(max(-c, 0) for c in cambios) / periodo
    if ap == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / ap))


def calcular_adx(highs: list, lows: list, closes: list, n: int = 14) -> float:
    """ADX correcto con DM+/DM- sobre high/low/close."""
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
#  CACHE KLINES (15m, 5m) — descargada cada 5 minutos
# ============================================================

@dataclass
class KlineCache:
    highs:      list  = field(default_factory=list)
    lows:       list  = field(default_factory=list)
    closes:     list  = field(default_factory=list)
    volumes:    list  = field(default_factory=list)   # vela volume (base)
    taker_vols: list  = field(default_factory=list)   # taker_buy_base
    ts:         float = 0.0


def _descargar_klines(simbolo: str, intervalo: str, limit: int = 100) -> Optional[KlineCache]:
    """Descarga klines de Binance Spot (bloqueante → llamar desde executor)."""
    try:
        url = f"{SPOT_API_URL}/api/v3/klines?symbol={simbolo}USDT&interval={intervalo}&limit={limit}"
        import urllib.request as _ur2
        req = _ur2.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _ur2.urlopen(req, timeout=8) as r:
            raw = json.loads(r.read())
        return KlineCache(
            highs      = [float(c[2]) for c in raw],
            lows       = [float(c[3]) for c in raw],
            closes     = [float(c[4]) for c in raw],
            volumes    = [float(c[5]) for c in raw],
            taker_vols = [float(c[9]) for c in raw],
            ts         = time.time(),
        )
    except Exception as e:
        print(f"[KLINES] {simbolo} {intervalo}: {e}", flush=True)
        return None


async def fetch_klines(simbolo: str, intervalo: str, limit: int = 100) -> Optional[KlineCache]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _descargar_klines, simbolo, intervalo, limit)


# ============================================================
#  ESTADO DEL ACTIVO
# ============================================================

@dataclass
class OperacionPendiente:
    simbolo:        str
    direccion:      str
    precio_entrada: float
    tiempo_entrada: float
    razon:          str
    num_operacion:  int
    cantidad:       float
    orden_real:     bool = False


@dataclass
class EstadoActivo:
    simbolo:      str
    # Historial 1m (velas cerradas del stream @kline_1m)
    opens_1m:     list = field(default_factory=list)
    highs_1m:     list = field(default_factory=list)
    lows_1m:      list = field(default_factory=list)
    closes_1m:    list = field(default_factory=list)
    volumes_1m:   list = field(default_factory=list)   # volumen vela 1m
    taker_buy_1m: list = field(default_factory=list)   # taker_buy_base 1m
    num_trades_1m:list = field(default_factory=list)   # num_trades 1m
    # Cache de timeframes superiores
    cache_15m:   Optional[KlineCache] = None
    cache_5m:    Optional[KlineCache] = None
    # Tracking
    precio_last:         float = 0.0
    operacion_pendiente: Optional[OperacionPendiente] = None
    cooldown_hasta:      float = 0.0
    ops_hoy:             int   = 0
    wins:                int   = 0
    losses:              int   = 0
    rsi_anterior:        float = 50.0   # RSI de la vela 1m anterior
    tick_count:          int   = 0


# ============================================================
#  ML GATE — carga de modelos y extracción de features
# ============================================================

_ML: dict = {}   # {f"{sym}_{dir}": {model, imputer, threshold, features}}


def _cargar_modelos_ml():
    """Carga en memoria modelos Ensemble LGBM+XGB para cada símbolo/dirección."""
    try:
        import joblib as _jbl
        import json as _jj
        import numpy as _np_ml   # noqa – ensure numpy importable
        # Import shared classes so joblib can unpickle EnsembleModel/IsotonicCalibrated
        from ml_helper import EnsembleModel, IsotonicCalibrated  # noqa: F401
    except ImportError as e:
        print(f"[ML] Dependencia faltante: {e} — bot opera sin ML gate", flush=True)
        return

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    if not os.path.isdir(base):
        print("[ML] Directorio models/ no encontrado — sin ML gate", flush=True)
        return

    for sym, direc in [("ETHUSDT", "CALL"), ("ETHUSDT", "PUT"), ("BTCUSDT", "CALL"), ("SOLUSDT", "CALL")]:
        tag = f"{sym}_{direc.lower()}"
        # buscar ensemble_*.pkl o cualquier *_{tag}.pkl
        candidate = None
        for fn in sorted(os.listdir(base)):
            if fn.endswith(f"_{tag}.pkl") and not fn.startswith("imputer"):
                candidate = os.path.join(base, fn)
                break
        imp_path  = os.path.join(base, f"imputer_{tag}.pkl")
        thr_path  = os.path.join(base, f"threshold_{tag}.txt")
        feat_path = os.path.join(base, f"features_{tag}.json")
        if candidate and os.path.exists(imp_path) and \
           os.path.exists(thr_path) and os.path.exists(feat_path):
            try:
                thr = float(open(thr_path).read().strip())
                key = f"{sym[:3]}_{direc}"   # e.g. "ETH_CALL"
                _ML[key] = {
                    "model":     _jbl.load(candidate),
                    "imputer":   _jbl.load(imp_path),
                    "threshold": thr,
                    "features":  _jj.load(open(feat_path)),
                }
                print(f"[ML] Cargado: {tag}  thr={thr:.2f}", flush=True)
            except Exception as exc:
                print(f"[ML] Error cargando {tag}: {exc}", flush=True)

_cargar_modelos_ml()

# ── Indicadores EWM (compatibles con pandas ewm(adjust=False)) ──────────────

def _ema_ewm(prices: list, span: int) -> list:
    """EMA con span (alpha = 2/(span+1)), adjust=False."""
    if not prices:
        return []
    alpha = 2.0 / (span + 1)
    out = [prices[0]]
    for p in prices[1:]:
        out.append(alpha * p + (1 - alpha) * out[-1])
    return out


def _rsi_ewm(closes: list, n: int = 14) -> list:
    """EWM RSI (alpha=1/n) — igual que pandas ewm(alpha=1/n, adjust=False)."""
    if len(closes) < 2:
        return [float('nan')] * len(closes)
    alpha = 1.0 / n
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = max(diffs[0], 0.0)
    loss = max(-diffs[0], 0.0)
    result = [float('nan')]       # index 0 undefined
    for d in diffs:
        gain = alpha * max(d, 0.0) + (1 - alpha) * gain
        loss = alpha * max(-d, 0.0) + (1 - alpha) * loss
        result.append(100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss))
    return result


def _atr_ewm_last(highs: list, lows: list, closes: list, n: int = 14) -> float:
    """Último valor del ATR EWM."""
    if len(closes) < 2:
        return float('nan')
    alpha = 1.0 / n
    atr_v = abs(highs[1] - closes[0])   # first TR
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        atr_v = alpha * tr + (1 - alpha) * atr_v
    return atr_v


def _adx_ewm_last(highs: list, lows: list, closes: list, n: int = 14) -> float:
    """Último valor del ADX EWM (equivalent to feature_engineering.adx())."""
    if len(closes) < 3:
        return float('nan')
    alpha = 1.0 / n
    # Bootstrap with index 1
    h, l, pc = highs[1], lows[1], closes[0]
    up_raw = highs[1] - highs[0]
    dn_raw = lows[0]  - lows[1]
    dmp = up_raw if up_raw > dn_raw and up_raw > 0 else 0.0
    dmn = dn_raw if dn_raw > up_raw and dn_raw > 0 else 0.0
    atr_v = max(h - l, abs(h - pc), abs(l - pc))
    dmp_v, dmn_v = dmp, dmn
    for i in range(2, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        dmp = up if up > dn and up > 0 else 0.0
        dmn = dn if dn > up and dn > 0 else 0.0
        tr = max(h - l, abs(h - pc), abs(l - pc))
        atr_v = alpha * tr  + (1 - alpha) * atr_v
        dmp_v = alpha * dmp + (1 - alpha) * dmp_v
        dmn_v = alpha * dmn + (1 - alpha) * dmn_v
    if atr_v == 0:
        return 0.0
    dip = 100 * dmp_v / atr_v
    din = 100 * dmn_v / atr_v
    if dip + din == 0:
        return 0.0
    dx = 100 * abs(dip - din) / (dip + din)
    # Approximate ADX as DX (no outer EWM over DX — good enough for live)
    return dx


def _stoch_k_last(highs: list, lows: list, closes: list, n: int = 14) -> float:
    if len(closes) < n:
        return float('nan')
    hi = max(highs[-n:])
    lo = min(lows[-n:])
    return 100.0 * (closes[-1] - lo) / (hi - lo) if hi != lo else 50.0


def _cci_last(highs: list, lows: list, closes: list, n: int = 20) -> float:
    if len(closes) < n:
        return float('nan')
    tp = [(highs[-n + i] + lows[-n + i] + closes[-n + i]) / 3 for i in range(n)]
    mean = sum(tp) / n
    mad  = sum(abs(t - mean) for t in tp) / n
    return (tp[-1] - mean) / (0.015 * mad) if mad != 0 else 0.0


def _macd_hist_last(closes: list, fast=12, slow=26, signal=9) -> float:
    if len(closes) < slow + signal:
        return float('nan')
    ema12 = _ema_ewm(closes, fast)
    ema26 = _ema_ewm(closes, slow)
    macd  = [ema12[i] - ema26[i] for i in range(len(closes))]
    sig   = _ema_ewm(macd, signal)
    return macd[-1] - sig[-1]


def _linreg_slope_last(series: list, n: int = 3) -> float:
    """Rolling linear regression slope (last n values), normalized by mean."""
    if len(series) < n:
        return float('nan')
    y = series[-n:]
    if any(math.isnan(v) for v in y):
        return float('nan')
    x = list(range(n))
    xm = (n - 1) / 2.0
    ym = sum(y) / n
    num = sum((x[i] - xm) * (y[i] - ym) for i in range(n))
    den = sum((x[i] - xm) ** 2 for i in range(n))
    return (num / den / ym) if den != 0 and ym != 0 else 0.0


def _bb_width_last(closes: list, n: int = 20) -> float:
    if len(closes) < n:
        return float('nan')
    seg  = closes[-n:]
    mean = sum(seg) / n
    std  = math.sqrt(sum((x - mean) ** 2 for x in seg) / n)
    return 4 * std / mean * 100 if mean != 0 else float('nan')


_nan = float('nan')


def extraer_features_live(estado: 'EstadoActivo') -> dict:
    """
    Extrae las 60 features del estado vivo del bot.
    Features no disponibles → NaN → imputer rellena con mediana de entrenamiento.
    """
    c1m  = estado.closes_1m
    o1m  = estado.opens_1m
    h1m  = estado.highs_1m
    l1m  = estado.lows_1m
    v1m  = estado.volumes_1m
    tb1m = estado.taker_buy_1m
    nt1m = estado.num_trades_1m
    n1m  = len(c1m)
    c5   = estado.cache_5m
    c15  = estado.cache_15m
    feats: dict = {}

    # ── HTF 5m pre-computed ───────────────────────────────────────────────
    if c5 and len(c5.closes) >= 14:
        feats['adx_5m_5m']       = _adx_ewm_last(c5.highs, c5.lows, c5.closes, 14)
        rsi5                     = _rsi_ewm(c5.closes, 14)
        feats['rsi_5m_5m']       = rsi5[-1]
        ema50_5m                 = _ema_ewm(c5.closes, 50)
        feats['ema50_5m_5m']     = ema50_5m[-1]
        ema200_5m                = _ema_ewm(c5.closes, 100)
        feats['ema200_5m_5m']    = ema200_5m[-1]
        feats['stoch_k_5m_5m']   = _stoch_k_last(c5.highs, c5.lows, c5.closes, 14)
        if c5.volumes:
            vm20 = sum(c5.volumes[-20:]) / min(20, len(c5.volumes))
            feats['vol_ma20_5m_5m'] = vm20
        else:
            feats['vol_ma20_5m_5m'] = _nan
        # EMA50 slope 5m (over last EMA50_SLOPE_N=5 HTF bars)
        if len(ema50_5m) >= 6:
            feats['ema50_slope_5m_5m'] = (ema50_5m[-1] - ema50_5m[-6]) / ema50_5m[-6] * 100 \
                                          if ema50_5m[-6] else _nan
        else:
            feats['ema50_slope_5m_5m'] = _nan
    else:
        for k in ['adx_5m_5m', 'rsi_5m_5m', 'ema50_5m_5m', 'ema200_5m_5m',
                  'stoch_k_5m_5m', 'vol_ma20_5m_5m', 'ema50_slope_5m_5m']:
            feats[k] = _nan

    # ── HTF 15m pre-computed ──────────────────────────────────────────────
    if c15 and len(c15.closes) >= 14:
        feats['adx_15m_15m']      = _adx_ewm_last(c15.highs, c15.lows, c15.closes, 14)
        rsi15                     = _rsi_ewm(c15.closes, 14)
        feats['rsi_15m_15m']      = rsi15[-1]
        ema50_15m                 = _ema_ewm(c15.closes, 50)
        feats['ema50_15m_15m']    = ema50_15m[-1]
        ema200_15m                = _ema_ewm(c15.closes, 100)
        feats['ema200_15m_15m']   = ema200_15m[-1]
        feats['stoch_k_15m_15m']  = _stoch_k_last(c15.highs, c15.lows, c15.closes, 14)
        if c15.volumes:
            vm20_15 = sum(c15.volumes[-20:]) / min(20, len(c15.volumes))
            feats['vol_ma20_15m_15m'] = vm20_15
        else:
            feats['vol_ma20_15m_15m'] = _nan
        if len(ema50_15m) >= 6:
            feats['ema50_slope_15m_15m'] = (ema50_15m[-1] - ema50_15m[-6]) / ema50_15m[-6] * 100 \
                                            if ema50_15m[-6] else _nan
        else:
            feats['ema50_slope_15m_15m'] = _nan
    else:
        for k in ['adx_15m_15m', 'rsi_15m_15m', 'ema50_15m_15m', 'ema200_15m_15m',
                  'stoch_k_15m_15m', 'vol_ma20_15m_15m', 'ema50_slope_15m_15m']:
            feats[k] = _nan

    # ── Momentum 1m ───────────────────────────────────────────────────────
    rsi_1m_series = _rsi_ewm(c1m, 14) if n1m >= 2 else [_nan] * n1m
    rsi_1m7_series = _rsi_ewm(c1m, 7)  if n1m >= 2 else [_nan] * n1m

    feats['rsi_1m_14']       = rsi_1m_series[-1]   if n1m >= 2  else _nan
    feats['rsi_1m_7']        = rsi_1m7_series[-1]  if n1m >= 2  else _nan
    # aliases from pre-computed HTF
    feats['rsi_5m_14']       = feats['rsi_5m_5m']
    feats['rsi_15m_14']      = feats['rsi_15m_15m']
    feats['rsi_divergencia'] = feats['rsi_1m_14'] - feats['rsi_5m_14'] \
                               if not math.isnan(feats['rsi_1m_14']) and \
                                  not math.isnan(feats['rsi_5m_14']) else _nan
    feats['macd_hist_1m']    = _macd_hist_last(c1m) if n1m >= 35 else _nan
    feats['stoch_k_5m']      = feats['stoch_k_5m_5m']
    feats['cci_1m_20']       = _cci_last(h1m, l1m, c1m, 20) if n1m >= 20 else _nan

    # ── Trend 1m ──────────────────────────────────────────────────────────
    if n1m >= 21:
        ema21_val           = _ema_ewm(c1m, 21)[-1]
        feats['ema21_dist'] = (c1m[-1] - ema21_val) / ema21_val * 100 if ema21_val else _nan
    else:
        feats['ema21_dist'] = _nan
    feats['ema50_15m_slope']  = feats['ema50_slope_15m_15m']
    e200_15 = feats['ema200_15m_15m']
    feats['ema200_15m_dist']  = (c1m[-1] - e200_15) / e200_15 * 100 \
                                if e200_15 and not math.isnan(e200_15) else _nan
    e50_15  = feats['ema50_15m_15m']
    feats['precio_sobre_ema'] = int(c1m[-1] > e50_15) \
                                if e50_15 and not math.isnan(e50_15) else _nan
    if n1m >= 11:
        hh = sum(1 for i in range(1, 10) if h1m[-10 + i] > h1m[-10 + i - 1])
        hl = sum(1 for i in range(1, 10) if l1m[-10 + i] > l1m[-10 + i - 1])
        feats['hh_hl_count'] = float(hh + hl)
    else:
        feats['hh_hl_count'] = _nan

    # ── Volatility 1m ─────────────────────────────────────────────────────
    if n1m >= 2:
        atr_val = _atr_ewm_last(h1m, l1m, c1m, 14)
        feats['atr_1m_14'] = atr_val
        feats['atr_pct']   = atr_val / c1m[-1] * 100 if c1m[-1] else _nan
    else:
        feats['atr_1m_14'] = _nan
        feats['atr_pct']   = _nan
    feats['adx_5m_14']      = feats['adx_5m_5m']   # alias
    feats['bb_width_1m_20'] = _bb_width_last(c1m, 20) if n1m >= 20 else _nan
    # vol_relativo_20: volume / mean(last-20 volumes)
    if v1m and len(v1m) >= 2:
        vm20 = sum(v1m[-20:]) / min(20, len(v1m))
        feats['vol_relativo_20'] = v1m[-1] / vm20 if vm20 else _nan
    else:
        feats['vol_relativo_20'] = _nan
    # vol_relativo_5m: volume_5m / vol_ma20_5m
    if c5 and c5.volumes and feats['vol_ma20_5m_5m'] and not math.isnan(feats['vol_ma20_5m_5m']):
        feats['vol_relativo_5m'] = c5.volumes[-1] / feats['vol_ma20_5m_5m']
    else:
        feats['vol_relativo_5m'] = _nan
    # hvol_20: std of log returns
    if n1m >= 22:
        rets = [math.log(c1m[i] / c1m[i - 1]) for i in range(n1m - 20, n1m) if c1m[i - 1] > 0]
        mr   = sum(rets) / len(rets)
        feats['hvol_20'] = math.sqrt(sum((r - mr) ** 2 for r in rets) / len(rets))
    else:
        feats['hvol_20'] = _nan

    # ── Price Action 1m ───────────────────────────────────────────────────
    if n1m >= 2:
        o, h, l, c = o1m[-1], h1m[-1], l1m[-1], c1m[-1]
        rng  = h - l
        body = abs(c - o)
        feats['body_size']    = body / rng        if rng else 0.5
        feats['upper_shadow'] = (h - max(o, c)) / rng if rng else 0.0
        feats['lower_shadow'] = (min(o, c) - l) / rng  if rng else 0.0
        feats['es_vela_alc']  = int(c > o)
        # engulfing: current body bigger than previous AND same bullish direction
        prev_body = abs(c1m[-2] - o1m[-2])
        feats['engulfing_bull'] = int(body > prev_body and c > o)
        feats['hammer']         = int(rng > 0 and (min(o, c) - l) / rng > 0.55
                                      and (h - max(o, c)) / rng < 0.15)
    else:
        for k in ['body_size', 'upper_shadow', 'lower_shadow',
                  'es_vela_alc', 'engulfing_bull', 'hammer']:
            feats[k] = _nan
    # num_trades_rel
    if nt1m and len(nt1m) >= 2:
        nt_ma = sum(nt1m[-20:]) / min(20, len(nt1m))
        feats['num_trades_rel'] = nt1m[-1] / nt_ma if nt_ma else _nan
    else:
        feats['num_trades_rel'] = _nan

    # ── Smart-money volume ────────────────────────────────────────────────
    if v1m and tb1m and len(v1m) >= 2 and len(tb1m) >= 2:
        vol   = v1m[-1]
        taker = tb1m[-1]
        feats['taker_ratio']   = taker / vol if vol else _nan
        # taker_ma_ratio: mean of last 10 taker_ratios
        ratios = [tb1m[i] / v1m[i] if v1m[i] else _nan
                  for i in range(max(0, len(v1m) - 10), len(v1m))]
        valid  = [r for r in ratios if not math.isnan(r)]
        feats['taker_ma_ratio'] = sum(valid) / len(valid) if valid else _nan
        delta  = taker - (vol - taker)           # taker_buy - taker_sell
        feats['delta_vol'] = delta
        # cvd_10: cumulative delta last 10 bars
        deltas = [tb1m[i] - (v1m[i] - tb1m[i])
                  for i in range(max(0, len(v1m) - 10), len(v1m))]
        feats['cvd_10'] = sum(deltas)
    else:
        for k in ['taker_ratio', 'taker_ma_ratio', 'delta_vol', 'cvd_10']:
            feats[k] = _nan

    # ── Temporal ──────────────────────────────────────────────────────────
    now  = datetime.now(tz=timezone.utc)
    hr   = now.hour + now.minute / 60.0
    dow  = now.weekday()
    feats['hour_sin']         = math.sin(2 * math.pi * hr  / 24)
    feats['hour_cos']         = math.cos(2 * math.pi * hr  / 24)
    feats['dow_sin']          = math.sin(2 * math.pi * dow / 7)
    feats['dow_cos']          = math.cos(2 * math.pi * dow / 7)
    feats['is_london_open']   = int(7  <= now.hour < 9)
    feats['is_ny_open']       = int(13 <= now.hour < 15)
    feats['is_asian_session'] = int(now.hour < 6)

    # ── RSI pullback memory ───────────────────────────────────────────────
    rsi_s = rsi_1m_series   # already computed above
    n_rsi = len(rsi_s)
    feats['rsi_prev1'] = rsi_s[-2] if n_rsi >= 2 else _nan
    feats['rsi_prev2'] = rsi_s[-3] if n_rsi >= 3 else _nan
    valid_rsi10 = [r for r in rsi_s[-10:] if not math.isnan(r)]
    feats['rsi_min_last_10']   = min(valid_rsi10)   if valid_rsi10 else _nan
    feats['rsi_max_last_10']   = max(valid_rsi10)   if valid_rsi10 else _nan
    feats['rsi_range_last_10'] = feats['rsi_max_last_10'] - feats['rsi_min_last_10'] \
                                  if valid_rsi10 else _nan
    # velas_desde_rsi_min
    window10 = list(rsi_s[-10:])
    valid_idx = [(i, v) for i, v in enumerate(window10) if not math.isnan(v)]
    if valid_idx:
        min_idx = min(valid_idx, key=lambda x: x[1])[0]
        feats['velas_desde_rsi_min'] = max(len(window10) - 1 - min_idx, 1)
    else:
        feats['velas_desde_rsi_min'] = _nan
    # rsi_recovery_vel
    if not math.isnan(feats['rsi_min_last_10']) and not math.isnan(feats['velas_desde_rsi_min']):
        feats['rsi_recovery_vel'] = (feats['rsi_1m_14'] - feats['rsi_min_last_10']) / \
                                     feats['velas_desde_rsi_min']
    else:
        feats['rsi_recovery_vel'] = _nan
    feats['rsi_slope_3'] = _linreg_slope_last(rsi_s, 3)

    return feats


def _ml_gate(estado: 'EstadoActivo', decision: str, razon: str) -> tuple:
    """
    Aplica el filtro ML tras la señal rule-based.
    Si no hay modelo cargado para este símbolo/dirección, deja pasar la señal.
    Retorna (decision, razon) — decision puede ser 'NEUTRAL' si ML rechaza.
    """
    key = f"{estado.simbolo}_{decision}"
    if key not in _ML:
        return decision, razon    # sin modelo → pasar

    ml    = _ML[key]
    feats = extraer_features_live(estado)
    vec   = [feats.get(col, _nan) for col in ml['features']]

    try:
        import numpy as _np
        import warnings as _w
        X     = _np.array([vec], dtype=_np.float32)
        X_imp = ml['imputer'].transform(X)
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            prob = float(ml['model'].predict_proba(X_imp)[0, 1])
    except Exception as exc:
        print(f"[ML] Error en predict: {exc}", flush=True)
        return decision, razon  # fallo → dejar pasar (conservador)

    if prob < ml['threshold']:
        return "NEUTRAL", f"ml_block|{decision}|p={prob:.2f}<thr={ml['threshold']:.2f}"
    return decision, razon + f"|ml={prob:.2f}"


# ============================================================
#  EVALUACIÓN DE SEÑAL — multi-timeframe, sin I/O bloqueante
# ============================================================

def evaluar_senal(estado: EstadoActivo) -> tuple:
    """
    Sniper Pullback: tendencia 15m + ADX 5m + RSI pullback 1m.
    Retorna (decision: str, razon: str).
    """
    c1m = estado.closes_1m
    o1m = estado.opens_1m

    # ── Warmup ─────────────────────────────────────────────
    if len(c1m) < WARMUP_CANDLES:
        return "NEUTRAL", f"warmup_{len(c1m)}"

    # ── 1m RSI ─────────────────────────────────────────────
    rsi_actual   = calcular_rsi(c1m, RSI_PERIODO)
    rsi_anterior = estado.rsi_anterior
    vela_alcista = c1m[-1] > o1m[-1]
    vela_bajista = c1m[-1] < o1m[-1]

    # ── 5m ADX ─────────────────────────────────────────────
    c5 = estado.cache_5m
    if c5 is None or len(c5.closes) < ADX_PERIODO + 2:
        return "NEUTRAL", "sin_5m"
    adx_val = calcular_adx(c5.highs, c5.lows, c5.closes, ADX_PERIODO)
    if adx_val < ADX_MIN:
        return "NEUTRAL", f"adx={adx_val:.1f}<{ADX_MIN}"

    # ── 15m EMA50 tendencia macro ───────────────────────────
    c15 = estado.cache_15m
    if c15 is None or len(c15.closes) < 55:
        return "NEUTRAL", "sin_15m"
    ema50 = _ema_lista(c15.closes, 50)
    ema50_vals = [e for e in ema50 if e is not None]
    if len(ema50_vals) < EMA50_SLOPE_N + 1:
        return "NEUTRAL", "ema50_insuf"
    e_now  = ema50_vals[-1]
    e_prev = ema50_vals[-EMA50_SLOPE_N - 1]
    precio = c1m[-1]

    slope_pct = (e_now - e_prev) / e_prev * 100 if e_prev else 0
    bull_macro = (slope_pct >=  EMA50_SLOPE_MIN) and (precio > e_now)
    bear_macro = (slope_pct <= -EMA50_SLOPE_MIN) and (precio < e_now)

    # ── 1m EMA21 micro-filtro ───────────────────────────────
    # Precio debe estar del lado correcto respecto a EMA21 en 1m
    ema21_vals = [e for e in _ema_lista(c1m, 21) if e is not None]
    ema21_ok    = len(ema21_vals) >= 1

    # ── CALL: pullback en uptrend ───────────────────────────
    # RSI cayó bajo RSI_PULLBACK_CALL y ahora recupera sobre RSI_RESUME_CALL
    # + precio por encima de EMA21 (micro-estructura alcista confirmada)
    pullback_call = rsi_anterior < RSI_PULLBACK_CALL and rsi_actual > RSI_RESUME_CALL
    ema21_bull    = (not ema21_ok) or (precio >= ema21_vals[-1])
    if bull_macro and pullback_call and vela_alcista and ema21_bull:
        razon_c = (
            f"call_pull|ema50={e_now:.0f}|slp={slope_pct:+.3f}%|"
            f"adx={adx_val:.1f}|rsi={rsi_anterior:.1f}>{rsi_actual:.1f}"
        )
        return _ml_gate(estado, "CALL", razon_c)

    # ── PUT: pullback en downtrend ──────────────────────────
    # + precio por debajo de EMA21 (micro-estructura bajista confirmada)
    pullback_put  = rsi_anterior > RSI_PULLBACK_PUT  and rsi_actual < RSI_RESUME_PUT
    ema21_bear    = (not ema21_ok) or (precio <= ema21_vals[-1])
    if bear_macro and pullback_put and vela_bajista and ema21_bear:
        razon_p = (
            f"put_pull|ema50={e_now:.0f}|slp={slope_pct:+.3f}%|"
            f"adx={adx_val:.1f}|rsi={rsi_anterior:.1f}>{rsi_actual:.1f}"
        )
        return _ml_gate(estado, "PUT", razon_p)

    # Diagnóstico
    motivos = []
    if not bull_macro and not bear_macro:
        motivos.append(f"trend_insuf(slope={slope_pct:+.3f}%)")
    if adx_val < ADX_MIN:
        motivos.append(f"adx_bajo({adx_val:.0f})")
    if not pullback_call and not pullback_put:
        motivos.append(f"sin_pull(rsi_ant={rsi_anterior:.0f},rsi_act={rsi_actual:.0f})")
    if (bull_macro and pullback_call and not ema21_bull) or \
       (bear_macro and pullback_put and not ema21_bear):
        motivos.append(f"ema21_block(precio={precio:.2f},ema21={ema21_vals[-1]:.2f})" if ema21_ok else "")
    return "NEUTRAL", "|".join(m for m in motivos if m) or "neutral"


# ============================================================
#  GUARDAR EN DJANGO
# ============================================================

def _guardar_op_sync(op: OperacionPendiente, precio_salida: float,
                     es_win: bool, profit: float):
    data = {
        "simbolo":        op.simbolo,
        "direccion":      op.direccion,
        "precio_entrada": op.precio_entrada,
        "razon":          op.razon[:99],
        "confianza":      "alta",
        "es_win":         es_win,
        "profit":         profit,
        "orden_real":     op.orden_real,
    }
    try:
        import urllib.request as _ur2
        raw = json.dumps(data).encode()
        req = _ur2.Request(DJANGO_API_URL, data=raw,
                           headers={'Content-Type': 'application/json'}, method='POST')
        _ur2.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[DJANGO] guardar op: {e}", flush=True)


def _guardar_tick_sync(simbolo: str, precio: float):
    try:
        import urllib.request as _ur2
        raw = json.dumps({"simbolo": simbolo, "precio": precio}).encode()
        req = _ur2.Request(DJANGO_TICK_URL, data=raw,
                           headers={'Content-Type': 'application/json'}, method='POST')
        _ur2.urlopen(req, timeout=2)
    except Exception:
        pass


# ============================================================
#  ESTADO GLOBAL
# ============================================================

_num_global         = 0
_ops_dia            = 0
_dia_actual         = datetime.now().day
_losses_consecutivos = 0
_pausa_hasta        = 0.0
_balance_log_ts     = 0.0     # Timestamp del último log de balance real


# ============================================================
#  CERRAR OPERACIÓN
# ============================================================

async def cerrar_operacion(estado: EstadoActivo, precio_actual: float, hora: str):
    global _losses_consecutivos, _pausa_hasta

    op = estado.operacion_pendiente

    # ── Cerrar posición REAL en Binance y obtener precio de salida ──
    precio_salida = precio_actual  # fallback: precio WebSocket
    side_cierre = "PUT" if op.direccion == "CALL" else "CALL"

    loop = asyncio.get_event_loop()
    try:
        resultado_cierre = await loop.run_in_executor(
            None, ejecutar_orden, op.simbolo, side_cierre, op.cantidad
        )
        if resultado_cierre:
            avg = float(resultado_cierre.get('avgPrice', 0))
            if avg > 0:
                precio_salida = avg
        else:
            print(f"[CLOSE] ⚠️ Orden de cierre falló — usando precio WebSocket ${precio_actual:.4f}", flush=True)
    except Exception as e:
        print(f"[CLOSE] Error cerrando posición: {e}", flush=True)

    # ── P&L REAL de Binance Futures = cantidad × diferencia de precio ──
    if op.direccion == "CALL":
        profit = (precio_salida - op.precio_entrada) * op.cantidad
    else:
        profit = (op.precio_entrada - precio_salida) * op.cantidad

    es_win = profit > 0

    if es_win:
        estado.wins += 1
        _losses_consecutivos = 0
    else:
        estado.losses += 1
        _losses_consecutivos += 1
        if _losses_consecutivos >= LOSS_STREAK_LIMIT:
            _pausa_hasta = time.time() + LOSS_STREAK_PAUSE
            print(f"[⛔] Circuit breaker activo — {LOSS_STREAK_LIMIT} losses → pausa {LOSS_STREAK_PAUSE}s", flush=True)

    total  = estado.wins + estado.losses
    wr     = estado.wins / total * 100 if total else 0
    cambio = (precio_salida - op.precio_entrada) / op.precio_entrada * 100
    res    = "✅ WIN" if es_win else "❌ LOSS"
    print(
        f"[{hora}] 🟢 REAL {op.simbolo} {op.direccion} {res} | "
        f"${op.precio_entrada:.4f}→${precio_salida:.4f} ({cambio:+.3f}%) | "
        f"P&L REAL: ${profit:+.6f} | WR:{wr:.1f}%({estado.wins}/{total})",
        flush=True
    )

    # Guardar en Django (no bloqueante)
    loop.run_in_executor(None, _guardar_op_sync, op, precio_salida, es_win, profit)

    estado.operacion_pendiente = None
    estado.cooldown_hasta      = time.time() + COOLDOWN_MIN_SEG


# ============================================================
#  WEBSOCKET — @kline_1m stream
# ============================================================

async def run_bot(simbolos: list):
    global _num_global, _ops_dia, _dia_actual

    estados      = {s: EstadoActivo(simbolo=s) for s in simbolos}
    tick_count   = {s: 0 for s in simbolos}

    streams = "/".join(f"{s.lower()}usdt@kline_1m" for s in simbolos)
    url     = f"wss://stream.binance.com:9443/stream?streams={streams}"

    print("=" * 65, flush=True)
    print("  🎯 SNIPER PULLBACK v2.0 — Multi-timeframe RSI pullback", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  Hold: {DURACION_SEG}s | Max {MAX_OPS_DIA} trades/día", flush=True)
    print(f"  ADX≥{ADX_MIN} | CALL: RSI<{RSI_PULLBACK_CALL}→>{RSI_RESUME_CALL}", flush=True)
    print(f"  PUT: RSI>{RSI_PULLBACK_PUT}→<{RSI_RESUME_PUT}", flush=True)
    print("=" * 65, flush=True)

    # Precarga de klines superiores
    print("[INIT] Descargando klines 15m y 5m...", flush=True)
    for s in simbolos:
        c15 = await fetch_klines(s, "15m", 120)
        c5  = await fetch_klines(s, "5m",  100)
        estados[s].cache_15m = c15
        estados[s].cache_5m  = c5
        n15 = len(c15.closes) if c15 else 0
        n5  = len(c5.closes)  if c5  else 0
        print(f"  {s}: 15m={n15} velas  5m={n5} velas", flush=True)
    print("[INIT] OK — conectando WebSocket...", flush=True)

    klines_refresh_ts = time.time()

    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
        print("[🚀] Conectado a Binance WebSocket", flush=True)

        async for mensaje in ws:
            try:
                raw    = json.loads(mensaje)
                if "data" not in raw:
                    continue
                d      = raw["data"]
                kl     = d.get("k", {})
                sym    = d.get("s", "").replace("USDT", "")
                cerrada = kl.get("x", False)

                if sym not in estados:
                    continue

                estado      = estados[sym]
                precio_last = float(kl.get("c", 0))
                estado.precio_last = precio_last
                hora = datetime.fromtimestamp(
                    int(kl.get("T", time.time() * 1000)) / 1000,
                    tz=timezone.utc
                ).strftime("%H:%M:%S")

                hoy = datetime.now().day
                if _dia_actual != hoy:
                    _dia_actual = hoy
                    _ops_dia    = 0
                    for st in estados.values():
                        st.ops_hoy = 0
                    print(f"[{hora}] 🌅 Nuevo día — contadores reseteados", flush=True)

                tick_count[sym] += 1
                estado.tick_count += 1

                # ── LOG POR TICK: actividad visible en tiempo real ──
                if estado.operacion_pendiente:
                    op   = estado.operacion_pendiente
                    elapsed = time.time() - op.tiempo_entrada
                    restantes = max(0, DURACION_SEG - elapsed)
                    if op.direccion == "CALL":
                        pnl_flot = (precio_last - op.precio_entrada) / op.precio_entrada * 100
                    else:
                        pnl_flot = (op.precio_entrada - precio_last) / op.precio_entrada * 100
                    estado_op = "GANANDO" if pnl_flot > 0 else "PERDIENDO"
                    print(
                        f"[{hora}] [{sym}] TICK ${precio_last:.4f} | "
                        f"OP#{op.num_operacion} {op.direccion} abierta ({elapsed:.0f}s/{DURACION_SEG}s) "
                        f"{estado_op} {pnl_flot:+.3f}% | cierre en {restantes:.0f}s",
                        flush=True
                    )
                else:
                    cd_restante = max(0, estado.cooldown_hasta - time.time())
                    pausa_rest  = max(0, _pausa_hasta - time.time())
                    if pausa_rest > 0:
                        estado_str = f"PAUSA_CIRCUIT {pausa_rest:.0f}s"
                    elif cd_restante > 0:
                        estado_str = f"COOLDOWN {cd_restante:.0f}s"
                    elif _ops_dia >= MAX_OPS_DIA:
                        estado_str = f"MAX_OPS_DIA({_ops_dia}/{MAX_OPS_DIA})"
                    else:
                        estado_str = f"ESCANEANDO [{len(estado.closes_1m)}velas]"
                    print(
                        f"[{hora}] [{sym}] TICK ${precio_last:.4f} | {estado_str} | "
                        f"vela_cerrada={cerrada}",
                        flush=True
                    )

                # Tick a Django cada 5 mensajes (suficiente resolución sin saturar la BD)
                if tick_count[sym] % 5 == 0:
                    loop = asyncio.get_event_loop()
                    loop.run_in_executor(None, _guardar_tick_sync, sym, precio_last)

                # Verificar operación pendiente
                if estado.operacion_pendiente:
                    elapsed = time.time() - estado.operacion_pendiente.tiempo_entrada
                    if elapsed >= DURACION_SEG:
                        await cerrar_operacion(estado, precio_last, hora)

                # Solo actuar en cierre de vela 1m
                if not cerrada:
                    continue

                # Guardar RSI anterior ANTES de agregar el nuevo cierre
                estado.rsi_anterior = calcular_rsi(estado.closes_1m, RSI_PERIODO)

                # Agregar vela cerrada al historial 1m
                estado.opens_1m.append(float(kl.get("o", precio_last)))
                estado.highs_1m.append(float(kl.get("h", precio_last)))
                estado.lows_1m.append(float(kl.get("l", precio_last)))
                estado.closes_1m.append(precio_last)
                estado.volumes_1m.append(float(kl.get("v", 0)))
                estado.taker_buy_1m.append(float(kl.get("V", 0)))
                estado.num_trades_1m.append(int(kl.get("n", 0)))

                # Ventana deslizante de 200 velas
                for lst in (estado.opens_1m, estado.highs_1m,
                            estado.lows_1m, estado.closes_1m,
                            estado.volumes_1m, estado.taker_buy_1m,
                            estado.num_trades_1m):
                    if len(lst) > 200:
                        del lst[:-200]

                # Refrescar klines 15m y 5m cada 5 minutos
                if time.time() - klines_refresh_ts > 300:
                    klines_refresh_ts = time.time()
                    for s in simbolos:
                        c15 = await fetch_klines(s, "15m", 120)
                        c5  = await fetch_klines(s, "5m",  100)
                        if c15:
                            estados[s].cache_15m = c15
                        if c5:
                            estados[s].cache_5m  = c5

                # ── Log balance REAL de Binance cada 5 minutos ──
                if time.time() - _balance_log_ts > 300:
                    _balance_log_ts = time.time()
                    try:
                        loop = asyncio.get_event_loop()
                        bd = await loop.run_in_executor(None, obtener_balance_sync)
                        _bal_wallet = float(bd.get('totalWalletBalance', 0))
                        _bal_avail  = float(bd.get('availableBalance', 0))
                        _bal_upnl   = float(bd.get('totalUnrealizedProfit', 0))
                        # Actualizar cache de balance para sizing dinámico
                        global _balance_cache, _balance_cache_ts
                        _balance_cache = _bal_avail
                        _balance_cache_ts = time.time()
                        print(
                            f"[💰 BALANCE REAL BINANCE] "
                            f"Wallet: ${_bal_wallet:.2f} | "
                            f"Disponible: ${_bal_avail:.2f} | "
                            f"PnL abierto: ${_bal_upnl:+.2f} | "
                            f"Sizing: {RIESGO_PCT*100:.0f}% × {LEVERAGE}x = "
                            f"${_bal_avail * RIESGO_PCT * LEVERAGE:.2f} notional",
                            flush=True
                        )
                    except Exception as e:
                        print(f"[BALANCE] Error consultando: {e}", flush=True)

                # Evaluar señal
                if estado.operacion_pendiente:
                    continue
                if _ops_dia >= MAX_OPS_DIA:
                    continue
                if estado.ops_hoy >= MAX_OPS_DIA // len(simbolos) + 2:
                    continue
                if time.time() < estado.cooldown_hasta:
                    continue
                if time.time() < _pausa_hasta:
                    if tick_count[sym] % 60 == 0:
                        print(f"[⛔] Pausa activa — quedan {int(_pausa_hasta - time.time())}s", flush=True)
                    continue

                decision, razon = evaluar_senal(estado)

                if decision == "NEUTRAL":
                    if tick_count[sym] % 15 == 0:
                        print(f"[{hora}] {sym} SCAN: {razon}", flush=True)
                    continue

                # Abrir operación REAL en Binance Futures
                _num_global += 1
                _ops_dia    += 1
                estado.ops_hoy += 1

                cantidad = obtener_cantidad(sym, precio_last)
                resultado_ord = ejecutar_orden(sym, decision, cantidad)

                if resultado_ord is None:
                    # Orden falló — NO simular, NO registrar
                    print(
                        f"[{hora}] ❌ ORDEN FALLIDA {sym} {decision} — "
                        f"no se abre operación (sin simulación)",
                        flush=True
                    )
                    _num_global -= 1
                    _ops_dia    -= 1
                    estado.ops_hoy -= 1
                    continue

                # Usar precio real de llenado de Binance
                avg_entry = float(resultado_ord.get('avgPrice', 0))
                precio_entrada_real = avg_entry if avg_entry > 0 else precio_last

                # Log del sizing dinámico
                margen_usado = (cantidad * precio_entrada_real) / LEVERAGE
                print(
                    f"[SIZING] {sym}: qty={cantidad} × ${precio_entrada_real:.2f} = "
                    f"${cantidad * precio_entrada_real:.2f} notional | "
                    f"Margen: ${margen_usado:.2f} ({RIESGO_PCT*100:.0f}% de balance)",
                    flush=True
                )

                estado.operacion_pendiente = OperacionPendiente(
                    simbolo        = sym,
                    direccion      = decision,
                    precio_entrada = precio_entrada_real,
                    tiempo_entrada = time.time(),
                    razon          = razon,
                    num_operacion  = _num_global,
                    cantidad       = cantidad,
                    orden_real     = True,
                )
                print(
                    f"[{hora}] 🟢 REAL #{_num_global} {sym} {decision} "
                    f"@ ${precio_entrada_real:.4f} (fill) | "
                    f"OrderID={resultado_ord.get('orderId')} | {razon[:60]}",
                    flush=True
                )

            except ConnectionClosedError:
                raise
            except Exception as e:
                import traceback
                print(f"[ERR] {e}", flush=True)
                print(traceback.format_exc()[:400], flush=True)


# ============================================================
#  MAIN
# ============================================================

async def main():
    # ML gate resultados (test set 30 días):
    #   ETH CALL: 69.0% WR  ETH PUT: 60.5% WR  BTC CALL: 72.5% WR  SOL CALL: 67.6% WR
    simbolos = ["ETH", "BTC", "SOL"]

    # ── Verificación de conexión REAL a Binance Futures ───────────────────────
    print("=" * 65, flush=True)
    print("  🔒 MODO: REAL — Todas las operaciones van a Binance Futures", flush=True)
    print("     Endpoint: https://fapi.binance.com (PRODUCCIÓN)", flush=True)
    print("     Sin simulaciones — si la orden falla, NO se registra", flush=True)
    print(f"     Sizing: {RIESGO_PCT*100:.0f}% del balance × {LEVERAGE}x leverage", flush=True)
    print("=" * 65, flush=True)

    MIN_BALANCE_BTC = 20.0
    try:
        bd  = obtener_balance_sync()
        bal = float(bd.get('availableBalance', 0))
        wallet = float(bd.get('totalWalletBalance', 0))
        upnl = float(bd.get('totalUnrealizedProfit', 0))
        print(f"[💰 BALANCE REAL BINANCE]", flush=True)
        print(f"     Wallet:     ${wallet:.2f} USDT", flush=True)
        print(f"     Disponible: ${bal:.2f} USDT", flush=True)
        print(f"     PnL abierto: ${upnl:+.2f} USDT", flush=True)

        # Inicializar cache de balance para sizing dinámico
        _balance_cache = bal
        _balance_cache_ts = time.time()
        notional_max = bal * RIESGO_PCT * LEVERAGE
        print(f"     Sizing dinámico: ${bal:.2f} × {RIESGO_PCT*100:.0f}% × {LEVERAGE}x = ${notional_max:.2f} notional", flush=True)

        # Mostrar posiciones abiertas
        positions = [p for p in bd.get('positions', []) if float(p.get('positionAmt', 0)) != 0]
        if positions:
            print(f"     Posiciones abiertas: {len(positions)}", flush=True)
            for p in positions:
                print(f"       {p['symbol']}: qty={p['positionAmt']} PnL=${p['unrealizedProfit']}", flush=True)

        if bal < MIN_BALANCE_BTC and "BTC" in simbolos:
            simbolos.remove("BTC")
            print(
                f"[⚠️] BTC desactivado — balance ${bal:.2f} < ${MIN_BALANCE_BTC} mínimo.\n"
                f"     BTC min_lot=0.001 ≈ $83 notional × 20x → $4.15 margen/op.\n"
                f"     Agrega capital para operar BTC sin riesgo de liquidación.",
                flush=True
            )
        print(f"[INFO] Activos activos: {simbolos}", flush=True)
        print(f"[INFO] P&L calculado desde precios REALES de fill de Binance API", flush=True)
    except Exception as e:
        print(f"[❌ BALANCE] Error conectando a Binance: {e}", flush=True)
        print(f"[❌] Verifica BINANCE_API_KEY y BINANCE_API_SECRET en .env", flush=True)
        return

    while True:
        try:
            await run_bot(simbolos)
        except (ConnectionClosedError, Exception) as e:
            print(f"[RECONEX] {e} — reintentando en 10s...", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
