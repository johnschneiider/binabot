"""
BOT BINANCE - OPERACIONES DE 120 SEGUNDOS
Versión corregida con logs visibles
"""

import requests

def obtener_balance():
    global _config_cargada
    if not _config_cargada:
        raise Exception("Configuración no cargada.")
    global _config_cargada
    if not _config_cargada:
        raise Exception("Configuración no cargada.")
    url = "https://api.binance.com/api/v3/account"
    headers = {
        'X-MBX-APIKEY': os.getenv('BINANCE_API_KEY')
    }
    response = requests.get(url, headers=headers)
    return response.json()  # Proporciona el balance en formato JSON


import asyncio
import json
import time
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Tuple
import websockets
import statistics
import urllib.request

# ============================================================
#  CONFIGURACION
# ============================================================

DJANGO_API_URL = "https://vitalmix.com.co/api/binance/guardar/"
DJANGO_TICK_URL = "https://vitalmix.com.co/api/binance/tick/"


# Defaults (se sobrescriben desde la base de datos)
STAKE = 1.0
PAYOUT = 0.95
DURACION_SEGUNDOS = 120
COOLDOWN_TICKS = 10
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
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cd{estado.cooldown}", "media")
    
    if len(estado.precios) < 50:
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
    
    # EMA crossover
    ema_rapida_above_media = estado.ema_rapida > estado.ema_media
    ema_media_above_lenta = estado.ema_media > estado.ema_lenta
    tendencia_alcista = ema_rapida_above_media and ema_media_above_lenta
    
    ema_rapida_below_media = estado.ema_rapida < estado.ema_media
    ema_media_below_lenta = estado.ema_media < estado.ema_lenta
    tendencia_bajista = ema_rapida_below_media and ema_media_below_lenta
    
    # CALL: Cruce alcista (EMA rápida cruza por encima de EMA media) + RSI < 65
    if ema_rapida_above_media and rsi < 65:
        if estado.cooldown > 0:
            return ("NEUTRAL", f"cd{estado.cooldown}", "baja")
        estado.cooldown = 15
        return ("CALL", "ema_crossover_up", "alta")
    
    # PUT: Cruce bajista (EMA rápida cruza por debajo de EMA media) + RSI > 35
    if ema_rapida_below_media and rsi > 35:
        if estado.cooldown > 0:
            return ("NEUTRAL", f"cd{estado.cooldown}", "baja")
        estado.cooldown = 15
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
#  WEBSOCKET
# ============================================================

async def conectar_binance(simbolos):
    streams = [f"{sym.lower()}usdt@trade" for sym in simbolos]
    url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
    
    estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
    num_global = 0
    
    print("="*50, flush=True)
    print("  BINANCE BOT - 60 SEGUNDOS", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  Stake: ${STAKE} | Duración: {DURACION_SEGUNDOS}s", flush=True)
    print("="*50, flush=True)
    
    async with websockets.connect(url, ping_interval=30, ping_timeout=30) as ws:
        print("[OK] Conectado a Binance", flush=True)
        
        async for msg in ws:
            try:
                data = json.loads(msg)
                if 'data' not in data:
                    continue
                
                trade = data['data']
                simbolo = trade['s'].replace('USDT', '')
                precio = float(trade['p'])
                hora = datetime.fromtimestamp(trade['T']/1000, tz=timezone.utc).strftime('%H:%M:%S')
                
                if simbolo not in estados:
                    continue
                
                estado = estados[simbolo]
                estado.tick_count += 1
                
                # Guardar tick cada 10
                if estado.tick_count % 10 == 0:
                    guardar_tick(simbolo, precio)
                
                # Verificar pendientes
                verificar_pendientes(estado, precio, hora)
                
                # Recargar config cada 30 segundos
                await reload_config_if_needed()
                
                # Nueva señal
                if estado.operacion_pendiente is None:
                    decision, razon, confianza = evaluar_senal(estado, precio)
                    
                    if decision != "NEUTRAL":
                        num_global += 1
                        estado.operacion_pendiente = OperacionPendiente(
                            simbolo=simbolo,
                            direccion=decision,
                            precio_entrada=precio,
                            tiempo_entrada=time.time(),
                            razon=razon,
                            confianza=confianza,
                            num_operacion=num_global
                        )
                        print(f"[{hora}] {simbolo}: ENTRADA {decision} @ ${precio:.2f} | {razon}", flush=True)
                
            except Exception as e:
                print(f"ERROR: {e}", flush=True)


# ============================================================
#  MAIN
# ============================================================

async def main():
    await reload_config_if_needed()
    global _config_cargada
    _config_cargada = True
    await reload_config_if_needed()
    global _config_cargada
    global _config_cargada
    await reload_config_if_needed()
    _config_cargada = True
    simbolos = ["BTC", "ETH", "SOL", "XRP"]  # Múltiples activos

    while True:
        try:
            print("[CONECTANDO] Binance...")
            await conectar_binance(simbolos)
            balance = obtener_balance()
            print(f"Balance: {balance}", flush=True)
    global _config_cargada
    await reload_config_if_needed()
    _config_cargada = True
    simbolos = ["BTC", "ETH", "SOL", "XRP"]

    while True:
        try:
            await reload_config_if_needed()
            print("[CONECTANDO] Binance...")
            await conectar_binance(simbolos)
            balance = obtener_balance()
            print(f"Balance: {balance}", flush=True)
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[DESCONECTADO] {e}", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            await asyncio.sleep(10)
    global _config_cargada
    await reload_config_if_needed()
    _config_cargada = True
    simbolos = ["BTC", "ETH", "SOL", "XRP"]  # Múltiples activos

    while True:
        try:
            print("[CONECTANDO] Binance...")
            await conectar_binance(simbolos)
            balance = obtener_balance()
            print(f"Balance: {balance}", flush=True)
    await reload_config_if_needed()
    global _config_cargada
    _config_cargada = True
    simbolos = ["BTC", "ETH", "SOL", "XRP"]  # Múltiples activos
    while True:
        try:
            print("[CONECTANDO] Binance...")
            await conectar_binance(simbolos)
    await reload_config_if_needed()
    global _config_cargada
    _config_cargada = True

    simbolos = ["BTC", "ETH", "SOL", "XRP"]  # Múltiples activos

    while True:
        try:
            print("[CONECTANDO] Binance...")
            await conectar_binance(simbolos)
    global _config_cargada
    _config_cargada = False
    await reload_config_if_needed()
    simbolos = ["BTC", "ETH", "SOL", "XRP"]  # Múltiples activos
    while True:
        try:
            print("[CONECTANDO] Binance...")
            await conectar_binance(simbolos)
            balance = obtener_balance()
            print(f"Balance: {balance}", flush=True)
    try:
            await reload_config_if_needed()
    await reload_config_if_needed()
    global _config_cargada
    _config_cargada = True

    try:
    try:
            await reload_config_if_needed()
        global _config_cargada
    await reload_config_if_needed()
    global _config_cargada
    await reload_config_if_needed()
    global _config_cargada
    await reload_config_if_needed()
    await reload_config_if_needed()
    global _config_cargada
    await reload_config_if_needed()
    await reload_config_if_needed()
    global _config_cargada
    _config_cargada = True
    
    simbolos = ["BTC", "ETH", "SOL", "XRP"]  # Múltiples activos
    
    while True:
        try:
                    await reload_config_if_needed()
            print("[CONECTANDO] Binance...", flush=True)
            try:
                                        await conectar_binance(simbolos)
        
    balance = obtener_balance()
    print(f"Balance: {balance}", flush=True)
            balance = obtener_balance()
            print(f"Balance: {balance}", flush=True)
        balance = obtener_balance()
        print(f"Balance: {balance}", flush=True)
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[DESCONECTADO] {e}", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    # Cargar config ANTES de iniciar el loop async
    cargar_configuracion()
    asyncio.run(main())
