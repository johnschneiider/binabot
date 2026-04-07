"""
BINANCE FUTURES BOT - OPERACIONES DE 60 SEGUNDOS
Versión con trading real en Binance Futures
"""

from dotenv import load_dotenv
import os
load_dotenv()

import requests
import hmac
import hashlib
import time
import os

FUTURES_API_URL = "https://fapi.binance.com"

def test_connection():
    """Test Binance API connection"""
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        print("[TEST] API key/secret NOT loaded!", flush=True)
        return False
    
    print(f"[TEST] API Key: {api_key[:8]}...", flush=True)
    print(f"[TEST] API Secret: {api_secret[:8]}...", flush=True)
    
    try:
        timestamp = int(time.time() * 1000)
        query = f'timestamp={timestamp}'
        sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f'{FUTURES_API_URL}/fapi/v2/account?{query}&signature={sig}'
        headers = {'X-MBX-APIKEY': api_key}
        
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"[TEST] Connection OK! Balance: {data.get('availableBalance')} USDT", flush=True)
            return True
        else:
            print(f"[TEST] API Error: {r.status_code} - {r.text[:100]}", flush=True)
            return False
    except Exception as e:
        print(f"[TEST] Exception: {e}", flush=True)
        return False

TEST_CONNECTION = test_connection()

MIN_NOTIONALS = {
    'BTC': 5.0, 'ETH': 5.0, 'BNB': 5.0, 'SOL': 5.0, 'XRP': 5.0,
    'ADA': 5.0, 'DOGE': 5.0, 'AVAX': 5.0, 'DOT': 5.0, 'MATIC': 5.0,
    'LINK': 5.0, 'LTC': 5.0, 'UNI': 5.0, 'ATOM': 5.0, 'XLM': 5.0,
    'ETC': 5.0, 'XMR': 5.0, 'TRX': 5.0, 'FIL': 5.0, 'APE': 5.0,
    'NEAR': 5.0, 'ALGO': 5.0, 'VET': 5.0, 'ICP': 5.0, 'HBAR': 5.0,
    'SAND': 5.0, 'MANA': 5.0, 'AXS': 5.0, 'FTM': 5.0, 'AAVE': 5.0,
}

def obtener_cantidad(simbolo):
    """Calcula cantidad basada en min notional de cada symbol"""
    min_notional = MIN_NOTIONALS.get(simbolo.upper(), 5.0)
    return int(min_notional)

def configurar_leverage_y_margin(simbolo, api_key, api_secret):
    """Configura leverage y margin type para el simbolo"""
    try:
        timestamp = int(time.time() * 1000)
        symbol = f"{simbolo}USDT"
        
        # Set leverage to 20x
        params_leverage = {
            "symbol": symbol,
            "leverage": 20,
            "timestamp": timestamp
        }
        query_leverage = "&".join([f"{k}={v}" for k, v in sorted(params_leverage.items())])
        sig_leverage = hmac.new(api_secret.encode(), query_leverage.encode(), hashlib.sha256).hexdigest()
        url_leverage = f"{FUTURES_API_URL}/fapi/v1/leverage?{query_leverage}&signature={sig_leverage}"
        headers = {'X-MBX-APIKEY': api_key}
        requests.post(url_leverage, headers=headers, timeout=10)
        
        # Set margin type to CROSSED (1)
        params_margin = {
            "symbol": symbol,
            "marginType": 1,  # 1 = CROSSED, 2 = ISOLATED
            "timestamp": timestamp
        }
        query_margin = "&".join([f"{k}={v}" for k, v in sorted(params_margin.items())])
        sig_margin = hmac.new(api_secret.encode(), query_margin.encode(), hashlib.sha256).hexdigest()
        url_margin = f"{FUTURES_API_URL}/fapi/v1/marginType?{query_margin}&signature={sig_margin}"
        requests.post(url_margin, headers=headers, timeout=10)
        
    except Exception as e:
        pass  # Silently continue if config fails

def ejecutar_orden(simbolo, direccion, cantidad=None):
    """
    Ejecuta una orden real en Binance Futures
    direccion: 'CALL' (LONG/BUY) o 'PUT' (SHORT/SELL)
    """
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        print("[ERROR] API key no configurada", flush=True)
        return None
    
    # Auto-configurar leverage y margin type antes de operar
    configurar_leverage_y_margin(simbolo, api_key, api_secret)
    
    print(f"[TRADE] Intentando orden REAL para {simbolo} {direccion}...", flush=True)
    
    try:
        timestamp = int(time.time() * 1000)
        
        # Para Binance Futures: CALL = BUY (LONG), PUT = SELL (SHORT)
        if direccion == "CALL":
            side = "BUY"
        else:
            side = "SELL"
        
        # Parameters para orden market - sin positionSide para evitar error
        params = {
            "symbol": f"{simbolo}USDT",
            "side": side,
            "type": "MARKET",
            "quantity": cantidad,
            "timestamp": timestamp
        }
        
        # Crear signature - para POST, incluir en query string
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Incluir signature en URL query string
        url = f"{FUTURES_API_URL}/fapi/v1/order?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': api_key}
        
        print(f"[TRADE] Enviando orden...", flush=True)
        response = requests.post(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"[TRADE] SUCCESS: orden REAL ejecutada para {simbolo} {direccion} | OrderID: {data.get('orderId')}", flush=True)
            return data
        else:
            print(f"[TRADE] ERROR Orden: {response.status_code}: {response.text}", flush=True)
            return None
            
    except Exception as e:
        print(f"[TRADE] ERROR EJECUTANDO: {e}", flush=True)
        return None

FUTURES_API_URL = "https://fapi.binance.com"
FUTURES_WS_URL = "wss://fstream.binance.com:9443/ws/"

def obtener_balance():
    global _config_cargada
    if not _config_cargada:
        raise Exception("Configuración no cargada.")
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    
    if not api_key or not api_secret:
        raise Exception("BINANCE_API_KEY o BINANCE_API_SECRET no configurados.")
    
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{FUTURES_API_URL}/fapi/v2/account?{query_string}&signature={signature}"
    headers = {
        'X-MBX-APIKEY': api_key
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Error API Binance Futures: {response.status_code} - {response.text}")
    
    return response.json()


import asyncio
import json
import time
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Tuple
import websockets
from websockets.exceptions import ConnectionClosedError
import statistics
import urllib.request

# ============================================================
#  CONFIGURACION
# ============================================================

DJANGO_API_URL = "http://127.0.0.1:8000/api/binance/guardar/"
DJANGO_TICK_URL = "http://127.0.0.1:8000/api/binance/tick/"


# Defaults (se sobrescriben desde la base de datos)
STAKE = 1.0
PAYOUT = 0.95
DURACION_SEGUNDOS = 60
COOLDOWN_TICKS = 50  # Cooldown más largo para estrategia conservadora (buscar 80% WR)
# Filtros para buscar >80% winrate
EMA_GAP_MIN = 0.15  # Gap más amplio para señales más fuertes
ADX_MIN = 25.0  # ADX más alto para tendencia fuerte
RSI_MIN = 30.0  # RSI más estricto
RSI_MAX = 70.0  # RSI más estricto
BB_MIN = 0.15
BB_MAX = 0.8

def cargar_configuracion():
    """Carga la configuración desde la base de datos"""
    global STAKE, PAYOUT, DURACION_SEGUNDOS, COOLDOWN_TICKS
    global EMA_GAP_MIN, ADX_MIN, RSI_MIN, RSI_MAX, BB_MIN, BB_MAX
    
    try:
        import os
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
        django.setup()
        from gestion_riesgo.models import ConfiguracionEstrategia
        
        tipo_activo = ConfiguracionEstrategia.get_tipo_activo(mercado='binance')
        config = ConfiguracionEstrategia.get_activa(tipo=tipo_activo, mercado='binance')
        STAKE = config.stake
        PAYOUT = config.payout
        DURACION_SEGUNDOS = config.duracion_segundos
        COOLDOWN_TICKS = config.cooldown_ticks
        EMA_GAP_MIN = config.ema_gap_min
        ADX_MIN = config.adx_min
        RSI_MIN = config.rsi_min
        RSI_MAX = config.rsi_max
        BB_MIN = config.bb_min
        BB_MAX = config.bb_max
        
        print(f"[CONFIG] Cargada: STAKE=${STAKE}, DUR={DURACION_SEGUNDOS}s, CD={COOLDOWN_TICKS}, EMA>={EMA_GAP_MIN}%, ADX>={ADX_MIN}, RSI={RSI_MIN}-{RSI_MAX}", flush=True)
    except Exception as e:
        print(f"[CONFIG] Error cargando config: {e} - usando defaults", flush=True)

# Recargar config cada 30 segundos
_ultimo_reload = 0
_config_cargada = False

_reload_lock = False

async def reload_config_if_needed():
    global _ultimo_reload, _config_cargada, _reload_lock
    import time
    ahora = time.time()
    if ahora - _ultimo_reload > 30 and _config_cargada and not _reload_lock:
        _reload_lock = True
        _ultimo_reload = ahora
        try:
            from asgiref.sync import sync_to_async
            from gestion_riesgo.models import ConfiguracionEstrategia
            
            @sync_to_async
            def get_config():
                tipo_activo = ConfiguracionEstrategia.get_tipo_activo(mercado='binance')
                config = ConfiguracionEstrategia.get_activa(tipo=tipo_activo, mercado='binance')
                return tipo_activo, config
            
            tipo_activo, config = await get_config()
            
            global STAKE, PAYOUT, DURACION_SEGUNDOS, COOLDOWN_TICKS
            global EMA_GAP_MIN, ADX_MIN, RSI_MIN, RSI_MAX, BB_MIN, BB_MAX
            STAKE = config.stake
            PAYOUT = config.payout
            DURACION_SEGUNDOS = config.duracion_segundos
            COOLDOWN_TICKS = config.cooldown_ticks
            EMA_GAP_MIN = config.ema_gap_min
            ADX_MIN = config.adx_min
            RSI_MIN = config.rsi_min
            RSI_MAX = config.rsi_max
            BB_MIN = config.bb_min
            BB_MAX = config.bb_max
            print(f"[CONFIG] Recargada ({tipo_activo}): EMA>={EMA_GAP_MIN}%, ADX>={ADX_MIN}, RSI={RSI_MIN}-{RSI_MAX}, CD={COOLDOWN_TICKS}", flush=True)
        except Exception as e:
            print(f"[CONFIG] Error recargando: {e}", flush=True)
        finally:
            _reload_lock = False


# ============================================================
#  OPERACIÓN PENDIENTE
# ============================================================

@dataclass
class OperacionPendiente:
    simbolo: str
    direccion: str
    precio_entrada: float
    tiempo_entrada: float
    razon: str
    confianza: str
    num_operacion: int
    orden_real: bool = False


# ============================================================
#  INDICADORES
# ============================================================

def calcular_ema(precio, ema_anterior, periodo):
    if ema_anterior is None:
        return precio
    alpha = 2.0 / (periodo + 1.0)
    return (alpha * precio) + ((1.0 - alpha) * ema_anterior)


def calcular_rsi(precios, periodo=14):
    if len(precios) < periodo + 1:
        return 50.0
    cambios = []
    for i in range(1, periodo + 1):
        cambios.append(precios[-i] - precios[-i-1])
    ganancias = [max(c, 0) for c in cambios]
    perdidas = [max(-c, 0) for c in cambios]
    avg_g = sum(ganancias) / periodo
    avg_p = sum(perdidas) / periodo
    if avg_p == 0:
        return 100.0
    rs = avg_g / avg_p
    return 100.0 - (100.0 / (1.0 + rs))


def calcular_bollinger(precios, periodo=20, num_std=2.0):
    if len(precios) < periodo:
        return 0.0, 0.0, 0.0
    arr = precios[-periodo:]
    media = sum(arr) / len(arr)
    std = statistics.stdev(arr) if len(arr) > 1 else 0.0
    return media + (num_std * std), media, media - (num_std * std)


def calcular_adx(precios, periodo=14):
    if len(precios) < periodo + 1:
        return 0.0
    up_moves = []
    down_moves = []
    for i in range(-periodo, 0):
        change = precios[i] - precios[i-1]
        if change > 0:
            up_moves.append(change)
            down_moves.append(0)
        else:
            up_moves.append(0)
            down_moves.append(abs(change))
    avg_up = sum(up_moves) / len(up_moves) if up_moves else 0
    avg_down = sum(down_moves) / len(down_moves) if down_moves else 0
    if avg_up + avg_down == 0:
        return 0.0
    di_plus = (avg_up / (avg_up + avg_down)) * 100
    di_minus = (avg_down / (avg_up + avg_down)) * 100
    return abs(di_plus - di_minus)


# ============================================================
#  ESTADO DEL ACTIVO
# ============================================================

@dataclass
class EstadoActivo:
    simbolo: str
    precios: list = field(default_factory=lambda: [])
    ema_rapida: Optional[float] = None
    ema_media: Optional[float] = None
    ema_lenta: Optional[float] = None
    rsi: float = 50.0
    adx: float = 0.0
    cooldown: int = 0
    total_ops: int = 0
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0
    operacion_pendiente: Optional[OperacionPendiente] = None
    tick_count: int = 0


# ============================================================
#  ESTRATEGIA
# ============================================================

DEBUG = True

def evaluar_senal(estado, precio):
    estado.precios.append(precio)
    if len(estado.precios) > 300:
        estado.precios = estado.precios[-300:]
    
    # Debug
    debug_sym = 'BTC'
    if estado.simbolo == debug_sym and len(estado.precios) % 5 == 0:
        print(f"[DEBUG] {debug_sym}: prices={len(estado.precios)}, cd={estado.cooldown}, rsi={estado.rsi:.1f}", flush=True)
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cd{estado.cooldown}", "media")
    
    if len(estado.precios) < 20:
        return ("NEUTRAL", "warmup", "baja")
    
    # EMA crossover simple (estrategia más robusta para timeframe 120s)
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 8)
    estado.ema_media = calcular_ema(precio, estado.ema_media, 21)
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 55)
    # Calcular RSI y EMA siempre desde API para mayor precision
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={estado.simbolo}USDT&interval=1m&limit=60"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            closes = [float(c[4]) for c in resp.json()]
            
            # RSI
            if len(closes) >= 15:
                rsi = calcular_rsi(closes[-15:])
            else:
                rsi = 50.0
            
            # EMA desde API
            ema8 = ema21 = ema55 = None
            for p in closes:
                k8 = 2 / 9
                k21 = 2 / 22
                k55 = 2 / 56
                ema8 = p * k8 + ema8 * (1 - k8) if ema8 else p
                ema21 = p * k21 + ema21 * (1 - k21) if ema21 else p
                ema55 = p * k55 + ema55 * (1 - k55) if ema55 else p
            
            # Override local EMA values
            estado.ema_rapida = ema8
            estado.ema_media = ema21
            estado.ema_lenta = ema55
            
        else:
            rsi = 50.0
    except Exception as e:
        rsi = 50.0
    estado.rsi = rsi
    
    # Debug signals
    if estado.simbolo == debug_sym and len(estado.precios) % 5 == 0:
        print(f"[DEBUG] {debug_sym}: ema8={estado.ema_rapida:.2f}, ema21={estado.ema_media:.2f}, ema55={estado.ema_lenta:.2f}, above={estado.ema_rapida > estado.ema_media}, above55={estado.ema_media > estado.ema_lenta}", flush=True)
    
    # EMA crossover
    ema_rapida_above_media = estado.ema_rapida > estado.ema_media
    ema_media_above_lenta = estado.ema_media > estado.ema_lenta
    tendencia_alcista = ema_rapida_above_media and ema_media_above_lenta
    
    ema_rapida_below_media = estado.ema_rapida < estado.ema_media
    ema_media_below_lenta = estado.ema_media < estado.ema_lenta
    tendencia_bajista = ema_rapida_below_media and ema_media_below_lenta
    
    # CALL: EMA8 > EMA21 > EMA55 + gap + trend + RSI sobrecompra (>70)
    if ema_rapida_above_media and ema_media_above_lenta:
        gap_pct = abs(estado.ema_rapida - estado.ema_media) / estado.ema_media * 100
        trend_gap = abs(estado.ema_media - estado.ema_lenta) / estado.ema_lenta * 100
        if gap_pct >= EMA_GAP_MIN and trend_gap >= EMA_GAP_MIN and rsi > RSI_MAX:
            print(f"[SEÑAL] {estado.simbolo}: CALL gap={gap_pct:.3f}% trend={trend_gap:.3f}% rsi={rsi:.1f}", flush=True)
            estado.cooldown = COOLDOWN_TICKS
            return ("CALL", "ema_crossover_up", "alta")
    
    # PUT: EMA8 < EMA21 < EMA55 + gap + trend + RSI sobreventa (<30)
    if ema_rapida_below_media and ema_media_below_lenta:
        gap_pct = abs(estado.ema_rapida - estado.ema_media) / estado.ema_media * 100
        trend_gap = abs(estado.ema_media - estado.ema_lenta) / estado.ema_lenta * 100
        if gap_pct >= EMA_GAP_MIN and trend_gap >= EMA_GAP_MIN and rsi < RSI_MIN:
            print(f"[SEÑAL] {estado.simbolo}: PUT gap={gap_pct:.3f}% trend={trend_gap:.3f}% rsi={rsi:.1f}", flush=True)
            estado.cooldown = COOLDOWN_TICKS
            return ("PUT", "ema_crossover_dn", "alta")
    
    return ("NEUTRAL", "sin_señal", "baja")


# ============================================================
#  GUARDAR EN DJANGO
# ============================================================

def guardar_operacion(simbolo, direccion, precio_entrada, precio_salida, razon, confianza, es_win, profit, num, orden_real=False):
    data = {
        "simbolo": simbolo,
        "direccion": direccion,
        "precio_entrada": precio_entrada,
        "razon": f"{razon}_out:{precio_salida:.2f}",
        "confianza": confianza,
        "es_win": es_win,
        "profit": profit,
        "orden_real": orden_real,
    }
    try:
        req = urllib.request.Request(
            DJANGO_API_URL,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        response = urllib.request.urlopen(req, timeout=5)
        return json.loads(response.read())
    except Exception as e:
        print(f"ERROR guardando: {e}", flush=True)
        return None


def guardar_tick(simbolo, precio):
    try:
        data = {"simbolo": simbolo, "precio": precio}
        req = urllib.request.Request(
            DJANGO_TICK_URL,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=2)
    except:
        pass


# ============================================================
#  VERIFICAR PENDIENTES
# ============================================================

def verificar_pendientes(estado, precio_actual, hora):
    if estado.operacion_pendiente is None:
        return
    
    op = estado.operacion_pendiente
    tiempo_transcurrido = time.time() - op.tiempo_entrada
    
    if tiempo_transcurrido >= DURACION_SEGUNDOS:
        es_win = (precio_actual > op.precio_entrada) if op.direccion == "CALL" else (precio_actual < op.precio_entrada)
        
        profit = (STAKE * PAYOUT) if es_win else -STAKE
        estado.total_ops += 1
        estado.profit += profit
        
        if es_win:
            estado.wins += 1
            estado.win_streak += 1
            estado.loss_streak = 0
        else:
            estado.losses += 1
            estado.loss_streak += 1
            estado.win_streak = 0
        
        # Cerrar posicion real en Binance si estaba abierta
        if getattr(op, 'orden_real', False):
            try:
                cantidad = obtener_cantidad(op.simbolo)
                direccion_opuesta = "PUT" if op.direccion == "CALL" else "CALL"
                resultado_cierre = ejecutar_orden(op.simbolo, direccion_opuesta, cantidad)
                if resultado_cierre:
                    print(f"[TRADE] Posicion cerrada para {op.simbolo}", flush=True)
            except Exception as e:
                print(f"[TRADE] Error cerrando posicion: {e}", flush=True)
        
        # Pasar el flag orden_real desde la operacion pendiente
        guardar_operacion(op.simbolo, op.direccion, op.precio_entrada, precio_actual, op.razon, op.confianza, es_win, profit, op.num_operacion, getattr(op, 'orden_real', False))
        
        wr = (estado.wins / estado.total_ops * 100) if estado.total_ops > 0 else 0
        resultado = "WIN" if es_win else "LOSS"
        tipo = "REAL" if getattr(op, 'orden_real', False) else "SIMULADO"
        print(f"[{hora}] {op.simbolo}: {op.direccion} | ${op.precio_entrada:.2f} -> ${precio_actual:.2f} | {resultado} ({profit:+.2f}) | WR:{wr:.1f}% | {tipo}", flush=True)
        estado.operacion_pendiente = None


# ============================================================
#  WEBSOCKET / POLLING
# ============================================================

async def conectar_binance(simbolos):
    """
    Binance Futures - alterna entre WebSocket y HTTP polling
    """
    estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
    num_global = 0
    
    print("="*50, flush=True)
    print("  BINANCE FUTURES BOT - 60 SEGUNDOS", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  Stake: ${STAKE} | Duración: {DURACION_SEGUNDOS}s", flush=True)
    print("="*50, flush=True)
    
    # USAR HTTP POLLING (más confiable)
    ultimo_precio = {sym: 0.0 for sym in simbolos}
    
    while True:
        try:
            print("[OK] Obteniendo precios via API...", flush=True)
            
            # Obtener precios actuales
            for sym in simbolos:
                try:
                    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}USDT"
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        precio = float(data['price'])
                        hora = datetime.now(timezone.utc).strftime('%H:%M:%S')
                        
                        ultimo_precio[sym] = precio
                        estado = estados[sym]
                        estado.tick_count += 1
                        
                        if estado.tick_count % 10 == 0:
                            guardar_tick(sym, precio)
                        
                        verificar_pendientes(estado, precio, hora)
                        
                        if estado.operacion_pendiente is None:
                            decision, razon, confianza = evaluar_senal(estado, precio)
                            
                            # Debug: ver estado de precios
                            if estado.tick_count % 10 == 0:
                                gap_pct = abs(estado.ema_rapida - estado.ema_media) / estado.ema_media * 100 if estado.ema_media else 0
                                trend_gap = abs(estado.ema_media - estado.ema_lenta) / estado.ema_lenta * 100 if estado.ema_lenta else 0
                                print(f"[DEBUG] {sym}: cd={estado.cooldown}, gap={gap_pct:.2f}%, trend={trend_gap:.2f}%, rsi={estado.rsi:.0f}, decision={decision}", flush=True)
                            
                            if decision != "NEUTRAL":
                                num_global += 1
                                # EJECUTAR ORDEN REAL EN BINANCE
                                cantidad_ajustada = obtener_cantidad(sym)
                                resultado_trade = ejecutar_orden(sym, decision, cantidad=cantidad_ajustada)
                                
                                estado.operacion_pendiente = OperacionPendiente(
                                    simbolo=sym,
                                    direccion=decision,
                                    precio_entrada=precio,
                                    tiempo_entrada=time.time(),
                                    razon=razon,
                                    confianza=confianza,
                                    num_operacion=num_global,
                                    orden_real=resultado_trade is not None
                                )
                                print(f"[{hora}] {sym}: ENTRADA {decision} @ ${precio:.2f} | {razon} | {'REAL' if resultado_trade else 'SIMULADO'}", flush=True)
                except Exception as e:
                    print(f"Error precio {sym}: {e}", flush=True)
            
            await asyncio.sleep(1)  # Poll cada segundo
            
        except Exception as e:
            import traceback
            print(f"[POLL ERROR] {e}", flush=True)
            print(f"[ERROR DETAIL] {traceback.format_exc()}", flush=True)
            await asyncio.sleep(5)


# ============================================================
#  MAIN
# ============================================================
#  MAIN
# ============================================================

async def main():
    await reload_config_if_needed()
    global _config_cargada
    _config_cargada = True
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    
    while True:
        try:
            await reload_config_if_needed()
            print("[OBTENIENDO BALANCE...]", flush=True)
            balance_data = obtener_balance()
            balance_usdt = float(balance_data.get('availableBalance', 0))
            print(f"BALANCE USDT: ${balance_usdt:.2f}", flush=True)
            print("[INICIANDO] Binance Futures...", flush=True)
            await conectar_binance(simbolos)
        except Exception as e:
            import traceback
            print(f"[ERROR] {e}", flush=True)
            print(f"[ERROR DETAIL] {traceback.format_exc()}", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    cargar_configuracion()
    asyncio.run(main())
