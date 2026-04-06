"""
BINANCE FUTURES BOT - OPERACIONES DE 60 SEGUNDOS
Versión para Binance Futures (CFD-like)
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

DJANGO_API_URL = "http://127.0.0.1:8000/gestion_riesgo/api/binance/guardar/"
DJANGO_TICK_URL = "http://127.0.0.1:8000/gestion_riesgo/api/binance/tick/"


# Defaults (se sobrescriben desde la base de datos)
STAKE = 1.0
PAYOUT = 0.95
DURACION_SEGUNDOS = 60
COOLDOWN_TICKS = 45  # Balance entre protección y oportunidad
# Filtros para buscar >80% winrate
EMA_GAP_MIN = 0.20  # 0.20% entre EMA8 y EMA21
EMA_GAP_MIN = 0.2
ADX_MIN = 20.0
RSI_MIN = 30.0
RSI_MAX = 70.0
BB_MIN = 0.2
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
    for i in range(-periodo, 0):
        cambios.append(precios[i] - precios[i-1])
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
    
    # Calcular RSI
    if len(estado.precios) >= 14:
        rsi = calcular_rsi(estado.precios[-14:])
    else:
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
    
    # CALL: EMA8 > EMA21 > EMA55 + gap > 0.15% + RSI > 60 (claro momentum alcista)
    if ema_rapida_above_media and ema_media_above_lenta:
        gap_pct = abs(estado.ema_rapida - estado.ema_media) / estado.ema_media * 100
        if gap_pct >= 0.15 and rsi > 60:  # Solo en sobrecompra clara
            print(f"[SEÑAL] {estado.simbolo}: CALL gap={gap_pct:.3f}% rsi={rsi:.1f}", flush=True)
            estado.cooldown = 50
            return ("CALL", "ema_crossover_up", "alta")
    
    # PUT: EMA8 < EMA21 < EMA55 + gap > 0.15% + RSI < 40 (claro momentum bajista)
    if ema_rapida_below_media and ema_media_below_lenta:
        gap_pct = abs(estado.ema_rapida - estado.ema_media) / estado.ema_media * 100
        if gap_pct >= 0.15 and rsi < 40:  # Solo en sobreventa clara
            print(f"[SEÑAL] {estado.simbolo}: PUT gap={gap_pct:.3f}% rsi={rsi:.1f}", flush=True)
            estado.cooldown = 50
            return ("PUT", "ema_crossover_dn", "alta")
    
    return ("NEUTRAL", "sin_señal", "baja")


# ============================================================
#  GUARDAR EN DJANGO
# ============================================================

def guardar_operacion(simbolo, direccion, precio_entrada, precio_salida, razon, confianza, es_win, profit, num):
    data = {
        "simbolo": simbolo,
        "direccion": direccion,
        "precio_entrada": precio_entrada,
        "razon": f"{razon}_out:{precio_salida:.2f}",
        "confianza": confianza,
        "es_win": es_win,
        "profit": profit,
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
        
        guardar_operacion(op.simbolo, op.direccion, op.precio_entrada, precio_actual, op.razon, op.confianza, es_win, profit, op.num_operacion)
        
        wr = (estado.wins / estado.total_ops * 100) if estado.total_ops > 0 else 0
        resultado = "WIN" if es_win else "LOSS"
        print(f"[{hora}] {op.simbolo}: {op.direccion} | ${op.precio_entrada:.2f} -> ${precio_actual:.2f} | {resultado} ({profit:+.2f}) | WR:{wr:.1f}%", flush=True)
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
                            if sym == 'BTC' and len(estado.precios) % 10 == 0:
                                print(f"[DEBUG] BTC: precios={len(estado.precios)}, ema8={estado.ema_rapida}, ema21={estado.ema_media}, rsi={estado.rsi}", flush=True)
                            
                            if decision != "NEUTRAL":
                                num_global += 1
                                estado.operacion_pendiente = OperacionPendiente(
                                    simbolo=sym,
                                    direccion=decision,
                                    precio_entrada=precio,
                                    tiempo_entrada=time.time(),
                                    razon=razon,
                                    confianza=confianza,
                                    num_operacion=num_global
                                )
                                print(f"[{hora}] {sym}: ENTRADA {decision} @ ${precio:.2f} | {razon}", flush=True)
                except Exception as e:
                    print(f"Error precio {sym}: {e}", flush=True)
            
            await asyncio.sleep(1)  # Poll cada segundo
            
        except Exception as e:
            print(f"[POLL ERROR] {e}", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[WS ERROR] {e}", flush=True)
            await asyncio.sleep(5)


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
