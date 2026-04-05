"""
BOT BINANCE V2 - ESTRATEGIA MEJORADA PARA 80% WINRATE
Implementa múltiples indicadores y filtros de calidad
"""

import asyncio
import json
import time
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import websockets
import statistics
import urllib.request
import numpy as np

# Importar estrategia ML
ML_ENABLED = False
aplicar_filtros_ml = None
recalcular_estrategia = None

def inicializar_ml():
    global ML_ENABLED, aplicar_filtros_ml, recalcular_estrategia
    try:
        import os
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
        django.setup()
        
        from binance_ml_strategy import aplicar_filtros_ml as _aml, recalcular_estrategia as _re
        aplicar_filtros_ml = _aml
        recalcular_estrategia = _re
        ML_ENABLED = True
        print("[ML] Sistema de Machine Learning habilitado", flush=True)
        return True
    except Exception as e:
        ML_ENABLED = False
        print(f"[ML] Error inicializando ML: {e} - continuando sin ML", flush=True)
        return False

# ============================================================
#  CONFIGURACION
# ============================================================

DJANGO_API_URL = "https://vitalmix.com.co/api/binance/guardar/"
DJANGO_TICK_URL = "https://vitalmix.com.co/api/binance/tick/"

# Configuración optimizada para 80% winrate
STAKE = 1.0
PAYOUT = 0.95
DURACION_SEGUNDOS = 120
COOLDOWN_TICKS = 25  # Aumentado para evitar overtrading
EMA_GAP_MIN = 0.15  # Gap mínimo entre EMAs
ADX_MIN = 25.0      # Tendencia más fuerte
RSI_MIN = 25.0      # Más estricto
RSI_MAX = 75.0      # Más estricto
BB_MIN = 0.15       # Posición en Bollinger más estricta
BB_MAX = 0.85

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
        COOLDOWN_TICKS = max(25, config.cooldown_ticks)  # Mínimo 25
        EMA_GAP_MIN = config.ema_gap_min
        ADX_MIN = max(25.0, config.adx_min)  # Mínimo 25
        RSI_MIN = config.rsi_min
        RSI_MAX = config.rsi_max
        BB_MIN = config.bb_min
        BB_MAX = config.bb_max
        
        print(f"[CONFIG] V2 Cargada: STAKE=${STAKE}, CD={COOLDOWN_TICKS}, ADX>={ADX_MIN}, RSI={RSI_MIN}-{RSI_MAX}", flush=True)
    except Exception as e:
        print(f"[CONFIG] Error: {e} - usando defaults optimizados", flush=True)

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
    indicadores: dict = field(default_factory=dict)

# ============================================================
#  INDICADORES AVANZADOS
# ============================================================

def calcular_ema(precio, ema_anterior, periodo):
    if ema_anterior is None:
        return precio
    alpha = 2.0 / (periodo + 1.0)
    return (alpha * precio) + ((1.0 - alpha) * ema_anterior)

def calcular_sma(precios, periodo):
    if len(precios) < periodo:
        return precios[-1] if precios else 0
    return sum(precios[-periodo:]) / periodo

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

def calcular_macd(precios, rapida=12, lenta=26, senal=9):
    if len(precios) < lenta:
        return 0.0, 0.0, 0.0
    
    # EMAs para MACD
    ema_rapida = calcular_sma(precios[-rapida:], rapida)
    ema_lenta = calcular_sma(precios[-lenta:], lenta)
    
    macd_line = ema_rapida - ema_lenta
    
    # Línea de señal (EMA de 9 del MACD)
    if not hasattr(calcular_macd, 'signal_history'):
        calcular_macd.signal_history = []
    
    calcular_macd.signal_history.append(macd_line)
    if len(calcular_macd.signal_history) > senal:
        calcular_macd.signal_history = calcular_macd.signal_history[-senal:]
    
    signal_line = calcular_sma(calcular_macd.signal_history, min(senal, len(calcular_macd.signal_history)))
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

def calcular_bollinger(precios, periodo=20, num_std=2.0):
    if len(precios) < periodo:
        precio_actual = precios[-1] if precios else 0
        return precio_actual, precio_actual, precio_actual, 0.5
    
    arr = precios[-periodo:]
    media = sum(arr) / len(arr)
    std = statistics.stdev(arr) if len(arr) > 1 else 0.0
    
    banda_superior = media + (num_std * std)
    banda_inferior = media - (num_std * std)
    
    # Posición dentro de las bandas (0 = banda inferior, 1 = banda superior)
    precio_actual = precios[-1]
    if banda_superior - banda_inferior == 0:
        posicion = 0.5
    else:
        posicion = (precio_actual - banda_inferior) / (banda_superior - banda_inferior)
        posicion = max(0.0, min(1.0, posicion))
    
    return banda_superior, media, banda_inferior, posicion

def calcular_adx(precios, periodo=14):
    if len(precios) < periodo + 1:
        return 0.0
    
    up_moves = []
    down_moves = []
    true_ranges = []
    
    for i in range(-periodo, 0):
        high = max(precios[i-1], precios[i])
        low = min(precios[i-1], precios[i])
        close = precios[i]
        prev_close = precios[i-1]
        
        up_move = high - precios[i-1]
        down_move = precios[i-1] - low
        
        up_moves.append(max(up_move, 0) if up_move > down_move else 0)
        down_moves.append(max(down_move, 0) if down_move > up_move else 0)
        
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(true_range)
    
    avg_up = sum(up_moves) / len(up_moves) if up_moves else 0
    avg_down = sum(down_moves) / len(down_moves) if down_moves else 0
    avg_tr = sum(true_ranges) / len(true_ranges) if true_ranges else 1
    
    di_plus = (avg_up / avg_tr) * 100 if avg_tr > 0 else 0
    di_minus = (avg_down / avg_tr) * 100 if avg_tr > 0 else 0
    
    if di_plus + di_minus == 0:
        return 0.0
    
    dx = abs(di_plus - di_minus) / (di_plus + di_minus) * 100
    return dx

def calcular_stoch(precios, periodo=14):
    """Oscilador Estocástico"""
    if len(precios) < periodo:
        return 50.0
    
    arr = precios[-periodo:]
    highest = max(arr)
    lowest = min(arr)
    current = precios[-1]
    
    if highest - lowest == 0:
        return 50.0
    
    k_percent = ((current - lowest) / (highest - lowest)) * 100
    return k_percent

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
    stoch: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    bb_posicion: float = 0.5
    cooldown: int = 0
    total_ops: int = 0
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0
    operacion_pendiente: Optional[OperacionPendiente] = None
    tick_count: int = 0
    ultimo_precio: float = 0.0
    
    # Histórico de indicadores para análisis de tendencias
    rsi_history: list = field(default_factory=lambda: [])
    adx_history: list = field(default_factory=lambda: [])

# ============================================================
#  ESTRATEGIA AVANZADA
# ============================================================

def evaluar_senal_v2(estado, precio):
    """Estrategia mejorada con múltiples filtros"""
    estado.precios.append(precio)
    estado.ultimo_precio = precio
    
    if len(estado.precios) > 300:
        estado.precios = estado.precios[-300:]
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cooldown_{estado.cooldown}", "baja")
    
    if len(estado.precios) < 55:
        return ("NEUTRAL", "warmup", "baja")
    
    # Actualizar todos los indicadores
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 5)   # Más rápido
    estado.ema_media = calcular_ema(precio, estado.ema_media, 13)   # Fibonacci
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 34)   # Fibonacci
    
    estado.rsi = calcular_rsi(estado.precios, 14)
    estado.adx = calcular_adx(estado.precios, 14)
    estado.stoch = calcular_stoch(estado.precios, 14)
    
    macd_line, signal_line, histogram = calcular_macd(estado.precios)
    estado.macd = macd_line
    estado.macd_signal = signal_line
    
    banda_sup, banda_med, banda_inf, bb_pos = calcular_bollinger(estado.precios, 20, 2.0)
    estado.bb_posicion = bb_pos
    
    # Mantener histórico
    estado.rsi_history.append(estado.rsi)
    estado.adx_history.append(estado.adx)
    if len(estado.rsi_history) > 10:
        estado.rsi_history = estado.rsi_history[-10:]
    if len(estado.adx_history) > 10:
        estado.adx_history = estado.adx_history[-10:]
    
    # ============================================================
    #  FILTROS DE CALIDAD - DEBE PASAR TODOS
    # ============================================================
    
    # 1. Filtro ADX - Tendencia fuerte
    if estado.adx < ADX_MIN:
        return ("NEUTRAL", f"adx_bajo_{estado.adx:.1f}", "baja")
    
    # 2. Filtro volatilidad - Evitar mercados muy volátiles
    if len(estado.precios) >= 20:
        volatilidad = statistics.stdev(estado.precios[-20:]) / estado.precios[-1] * 100
        if volatilidad > 2.0:  # Más del 2% de volatilidad
            return ("NEUTRAL", f"volatilidad_alta_{volatilidad:.2f}", "baja")
    
    # 3. Filtro de momentum - MACD debe confirmar
    macd_momentum_ok = False
    if estado.macd > estado.macd_signal and histogram > 0:
        macd_momentum_ok = "bullish"
    elif estado.macd < estado.macd_signal and histogram < 0:
        macd_momentum_ok = "bearish"
    
    if not macd_momentum_ok:
        return ("NEUTRAL", "macd_sin_momentum", "baja")
    
    # ============================================================
    #  SEÑALES DE ENTRADA - MUY ESTRICTAS
    # ============================================================
    
    # Condición CALL - Todo debe alinearse alcista
    ema_tendencia_alcista = (estado.ema_rapida > estado.ema_media > estado.ema_lenta)
    rsi_no_sobrecomprado = (RSI_MIN < estado.rsi < 65)  # No muy alto
    bb_no_sobrecomprado = (estado.bb_posicion < 0.8)   # No en banda superior
    stoch_ok_call = (estado.stoch < 80)  # Estocástico no sobrecomprado
    macd_alcista = (macd_momentum_ok == "bullish")
    
    # Gap entre EMAs suficiente (evita señales en rangos)
    ema_gap = abs(estado.ema_rapida - estado.ema_lenta) / estado.ema_lenta * 100
    gap_suficiente = ema_gap > EMA_GAP_MIN
    
    if (ema_tendencia_alcista and rsi_no_sobrecomprado and bb_no_sobrecomprado 
        and stoch_ok_call and macd_alcista and gap_suficiente):
        
        # FILTRO ML ADICIONAL
        if ML_ENABLED:
            ml_aprobado, ml_razon = aplicar_filtros_ml(estado.simbolo, "CALL", 
                                                      f"multi_alcista_adx{estado.adx:.0f}", precio)
            if not ml_aprobado:
                return ("NEUTRAL", f"ml_rechazo_{ml_razon}", "baja")
            
        estado.cooldown = COOLDOWN_TICKS
        confianza = "muy_alta" if estado.adx > 30 and ema_gap > 0.3 else "alta"
        return ("CALL", f"multi_alcista_adx{estado.adx:.0f}_gap{ema_gap:.2f}", confianza)
    
    # Condición PUT - Todo debe alinearse bajista  
    ema_tendencia_bajista = (estado.ema_rapida < estado.ema_media < estado.ema_lenta)
    rsi_no_sobrevendido = (35 < estado.rsi < RSI_MAX)  # No muy bajo
    bb_no_sobrevendido = (estado.bb_posicion > 0.2)    # No en banda inferior
    stoch_ok_put = (estado.stoch > 20)  # Estocástico no sobrevendido
    macd_bajista = (macd_momentum_ok == "bearish")
    
    if (ema_tendencia_bajista and rsi_no_sobrevendido and bb_no_sobrevendido 
        and stoch_ok_put and macd_bajista and gap_suficiente):
        
        # FILTRO ML ADICIONAL
        if ML_ENABLED:
            ml_aprobado, ml_razon = aplicar_filtros_ml(estado.simbolo, "PUT", 
                                                      f"multi_bajista_adx{estado.adx:.0f}", precio)
            if not ml_aprobado:
                return ("NEUTRAL", f"ml_rechazo_{ml_razon}", "baja")
            
        estado.cooldown = COOLDOWN_TICKS
        confianza = "muy_alta" if estado.adx > 30 and ema_gap > 0.3 else "alta"
        return ("PUT", f"multi_bajista_adx{estado.adx:.0f}_gap{ema_gap:.2f}", confianza)
    
    return ("NEUTRAL", "condiciones_insuficientes", "baja")

# ============================================================
#  GUARDAR EN DJANGO
# ============================================================

def guardar_operacion(simbolo, direccion, precio_entrada, precio_salida, razon, confianza, es_win, profit, num):
    data = {
        "simbolo": simbolo,
        "direccion": direccion,
        "precio_entrada": precio_entrada,
        "razon": f"v2_{razon}_out:{precio_salida:.2f}",
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
#  VERIFICAR PENDIENTES CON STOP LOSS
# ============================================================

def verificar_pendientes_v2(estado, precio_actual, hora):
    if estado.operacion_pendiente is None:
        return
    
    op = estado.operacion_pendiente
    tiempo_transcurrido = time.time() - op.tiempo_entrada
    
    # Stop Loss dinámico al 50% del tiempo
    if tiempo_transcurrido >= DURACION_SEGUNDOS * 0.5:
        # Revisar si la operación va muy mal
        if op.direccion == "CALL":
            perdida_actual = (precio_actual - op.precio_entrada) / op.precio_entrada
            if perdida_actual < -0.005:  # -0.5% stop loss
                es_win = False
                razon_salida = f"{op.razon}_stoploss"
                print(f"[{hora}] {op.simbolo}: STOP LOSS {op.direccion} @ {precio_actual:.2f} ({perdida_actual*100:.2f}%)", flush=True)
        else:  # PUT
            perdida_actual = (op.precio_entrada - precio_actual) / op.precio_entrada
            if perdida_actual < -0.005:  # -0.5% stop loss
                es_win = False
                razon_salida = f"{op.razon}_stoploss"
                print(f"[{hora}] {op.simbolo}: STOP LOSS {op.direccion} @ {precio_actual:.2f} ({perdida_actual*100:.2f}%)", flush=True)
    
    # Cierre normal al tiempo completo
    if tiempo_transcurrido >= DURACION_SEGUNDOS:
        if op.direccion == "CALL":
            es_win = precio_actual > op.precio_entrada
        else:
            es_win = precio_actual < op.precio_entrada
        
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
        
        # Guardar con razón V2
        razon_completa = op.razon if 'stoploss' not in locals() else razon_salida
        guardar_operacion(op.simbolo, op.direccion, op.precio_entrada, precio_actual, 
                         razon_completa, op.confianza, es_win, profit, op.num_operacion)
        
        wr = (estado.wins / estado.total_ops * 100) if estado.total_ops > 0 else 0
        resultado = "WIN" if es_win else "LOSS"
        cambio = ((precio_actual - op.precio_entrada) / op.precio_entrada) * 100
        
        print(f"[{hora}] {op.simbolo}: V2 {op.direccion} | ${op.precio_entrada:.2f}→${precio_actual:.2f} | {resultado} ({profit:+.2f}) | {cambio:+.3f}% | WR:{wr:.1f}%", flush=True)
        estado.operacion_pendiente = None

# ============================================================
#  WEBSOCKET
# ============================================================

async def conectar_binance_v2(simbolos):
    streams = [f"{sym.lower()}usdt@trade" for sym in simbolos]
    url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
    
    estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
    num_global = 0
    ultima_recalibracion = time.time()
    
    print("="*60, flush=True)
    print("  BINANCE BOT V2 + ML - ESTRATEGIA OPTIMIZADA 80% WINRATE", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  Stake: ${STAKE} | Duración: {DURACION_SEGUNDOS}s | Cooldown: {COOLDOWN_TICKS}", flush=True)
    print(f"  Filtros: ADX≥{ADX_MIN}, RSI:{RSI_MIN}-{RSI_MAX}, EMA_GAP≥{EMA_GAP_MIN}%", flush=True)
    print(f"  ML: {'ACTIVADO' if ML_ENABLED else 'DESACTIVADO'}", flush=True)
    print("="*60, flush=True)
    
    async with websockets.connect(url, ping_interval=30, ping_timeout=30) as ws:
        print("[OK] Conectado a Binance V2", flush=True)
        
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
                
                # Guardar tick cada 15 (menos frecuente)
                if estado.tick_count % 15 == 0:
                    guardar_tick(simbolo, precio)
                
                # Verificar pendientes con stop loss
                verificar_pendientes_v2(estado, precio, hora)
                
                # Recalibración ML cada 30 minutos
                if ML_ENABLED and time.time() - ultima_recalibracion > 1800:
                    if recalcular_estrategia():
                        ultima_recalibracion = time.time()
                        print(f"[{hora}] 🧠 ML recalibrado", flush=True)
                
                # Nueva señal solo si no hay operación pendiente
                if estado.operacion_pendiente is None:
                    decision, razon, confianza = evaluar_senal_v2(estado, precio)
                    
                    if decision != "NEUTRAL":
                        num_global += 1
                        estado.operacion_pendiente = OperacionPendiente(
                            simbolo=simbolo,
                            direccion=decision,
                            precio_entrada=precio,
                            tiempo_entrada=time.time(),
                            razon=razon,
                            confianza=confianza,
                            num_operacion=num_global,
                            indicadores={
                                'rsi': estado.rsi,
                                'adx': estado.adx,
                                'stoch': estado.stoch,
                                'bb_pos': estado.bb_posicion,
                                'macd': estado.macd
                            }
                        )
                        print(f"[{hora}] {simbolo}: V2 {decision} @ ${precio:.2f} | {razon} | RSI:{estado.rsi:.0f} ADX:{estado.adx:.0f} BB:{estado.bb_posicion:.2f}", flush=True)
                
            except Exception as e:
                print(f"ERROR V2: {e}", flush=True)

# ============================================================
#  MAIN
# ============================================================

async def main_v2():
    # Inicializar ML
    inicializar_ml()
    
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    
    while True:
        try:
            print("[CONECTANDO V2] Binance...", flush=True)
            await conectar_binance_v2(simbolos)
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[DESCONECTADO V2] {e}", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERROR V2] {e}", flush=True)
            await asyncio.sleep(10)

if __name__ == "__main__":
    cargar_configuracion()
    asyncio.run(main_v2())