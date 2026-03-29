"""
BOT TRADING - ALLTICK FOREX
Opera con ticks reales de Forex usando AllTick API
"""

import asyncio
import json
import time
import sys
import statistics
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Tuple
import websocket
import threading

# ============================================================
#  CONFIGURACION
# ============================================================

# Leer token desde archivo
try:
    with open('api_alltick.txt', 'r') as f:
        ALLTICK_TOKEN = f.read().strip()
except:
    ALLTICK_TOKEN = "testtoken"

DJANGO_API_URL = "http://127.0.0.1:8000/api/trading/guardar/"
DJANGO_TICK_URL = "http://127.0.0.1:8000/api/trading/tick/"

# Defaults
STAKE = 1.0
PAYOUT = 0.95
DURACION_SEGUNDOS = 60
COOLDOWN_TICKS = 150
EMA_GAP_MIN = 0.2
ADX_MIN = 20.0
RSI_MIN = 30.0
RSI_MAX = 70.0
BB_MIN = 0.2
BB_MAX = 0.8

def cargar_configuracion():
    global STAKE, PAYOUT, DURACION_SEGUNDOS, COOLDOWN_TICKS
    global EMA_GAP_MIN, ADX_MIN, RSI_MIN, RSI_MAX, BB_MIN, BB_MAX
    
    try:
        import os
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
        django.setup()
        from trading.models import ConfiguracionTrading
        
        config = ConfiguracionTrading.get_activa()
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
        print(f"[CONFIG] Error: {e} - usando defaults", flush=True)


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
        diff = precios[i] - precios[i-1]
        up_moves.append(diff if diff > 0 else 0)
        down_moves.append(-diff if diff < 0 else 0)
    
    avg_up = sum(up_moves) / periodo
    avg_down = sum(down_moves) / periodo
    
    if avg_down == 0:
        return 25.0
    
    up_ratio = avg_up / avg_down
    dx = (abs(avg_up - avg_down) / (avg_up + avg_down)) * 100
    return dx


# ============================================================
#  ESTADO POR ACTIVO
# ============================================================

class EstadoActivo:
    def __init__(self, simbolo: str):
        self.simbolo = simbolo
        self.precios = []
        self.ema_rapida = None
        self.ema_media = None
        self.ema_lenta = None
        self.rsi = 50.0
        self.adx = 0.0
        self.cooldown = 0
        self.total_ops = 0
        self.wins = 0
        self.losses = 0
        self.profit = 0.0
        self.win_streak = 0
        self.loss_streak = 0
        self.operacion_pendiente: Optional[OperacionPendiente] = None
        self.tick_count = 0


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
    
    if len(estado.precios) < 60:
        return ("NEUTRAL", "warmup", "baja")
    
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 9)
    estado.ema_media = calcular_ema(precio, estado.ema_media, 21)
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 50)
    estado.rsi = calcular_rsi(estado.precios, 14)
    estado.adx = calcular_adx(estado.precios, 14)
    
    ema_gap = abs(estado.ema_media - estado.ema_lenta) / precio * 100
    tendencia_alcista = estado.ema_media > estado.ema_lenta
    tendencia_bajista = estado.ema_media < estado.ema_lenta
    
    momentum = 0.0
    if len(estado.precios) >= 15:
        momentum = (precio - estado.precios[-15]) / estado.precios[-15] * 100
    
    banda_sup, media_bb, banda_inf = calcular_bollinger(estado.precios, 20, 2.0)
    precio_vs_bb = 0.5
    if (banda_sup - banda_inf) > 0:
        precio_vs_bb = (precio - banda_inf) / (banda_sup - banda_inf)
    
    triple_alcista = estado.ema_rapida > estado.ema_media > estado.ema_lenta
    triple_bajista = estado.ema_rapida < estado.ema_media < estado.ema_lenta
    
    if DEBUG and estado.tick_count % 50 == 0:
        razones_falla = []
        if ema_gap < EMA_GAP_MIN:
            razones_falla.append(f"gap bajo({ema_gap:.3f}%)")
        if estado.adx < ADX_MIN:
            razones_falla.append(f"adx bajo({estado.adx:.0f})")
        if estado.rsi < RSI_MIN or estado.rsi > RSI_MAX:
            razones_falla.append(f"rsi {estado.rsi:.0f}")
        if not (triple_alcista or triple_bajista):
            razones_falla.append("no triple EMA")
        if precio_vs_bb < BB_MIN or precio_vs_bb > BB_MAX:
            razones_falla.append(f"bb extremo({precio_vs_bb:.2f})")
        
        if razones_falla:
            print(f"[{estado.simbolo}] NO ENTRA: {', '.join(razones_falla)}", flush=True)
        else:
            print(f"[{estado.simbolo}] CONDICIONES OK - evaluando entrada...", flush=True)
    
    if ema_gap < EMA_GAP_MIN:
        return ("NEUTRAL", "gap_bajo", "baja")
    if estado.adx < ADX_MIN:
        return ("NEUTRAL", "adx_bajo", "baja")
    if estado.rsi < RSI_MIN or estado.rsi > RSI_MAX:
        return ("NEUTRAL", "rsi_extremo", "baja")
    if not (triple_alcista or triple_bajista):
        return ("NEUTRAL", "no_triple", "baja")
    if precio_vs_bb < BB_MIN or precio_vs_bb > BB_MAX:
        return ("NEUTRAL", "bb_extremo", "baja")
    
    if triple_alcista and tendencia_alcista and momentum > 0:
        estado.cooldown = COOLDOWN_TICKS
        return ("CALL", "alineado_alc", "alta")
    
    if triple_bajista and tendencia_bajista and momentum < 0:
        estado.cooldown = COOLDOWN_TICKS
        return ("PUT", "alineado_baj", "alta")
    
    return ("NEUTRAL", "sin_señal", "baja")


# ============================================================
#  GUARDAR EN DJANGO
# ============================================================

def guardar_operacion(simbolo, direccion, precio_entrada, precio_salida, razon, confianza, es_win, profit, num):
    data = {
        "simbolo": simbolo,
        "direccion": direccion,
        "precio_entrada": precio_entrada,
        "razon": f"{razon}_out:{precio_salida:.5f}",
        "confianza": confianza,
        "es_win": es_win,
        "profit": profit,
    }
    try:
        import urllib.request
        req = urllib.request.Request(
            DJANGO_API_URL,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        response = urllib.request.urlopen(req, timeout=5)
        return json.loads(response.read())
    except Exception as e:
        print(f"[ERROR] Guardar operación: {e}", flush=True)
        return None


def guardar_tick(simbolo, precio):
    try:
        import urllib.request
        data = {"simbolo": simbolo, "precio": precio}
        req = urllib.request.Request(
            DJANGO_TICK_URL,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=3)
    except:
        pass


def verificar_pendientes(estado, precio_actual, hora):
    if estado.operacion_pendiente is None:
        return
    
    op = estado.operacion_pendiente
    tiempo_transcurrido = time.time() - op.tiempo_entrada
    
    if tiempo_transcurrido >= DURACION_SEGUNDOS:
        es_win = (op.direccion == "CALL" and precio_actual > op.precio_entrada) or \
                 (op.direccion == "PUT" and precio_actual < op.precio_entrada)
        
        profit = STAKE * PAYOUT if es_win else -STAKE
        
        resultado = guardar_operacion(
            op.simbolo, op.direccion, op.precio_entrada, precio_actual,
            op.razon, op.confianza, es_win, profit, op.num_operacion
        )
        
        if es_win:
            estado.wins += 1
            estado.win_streak += 1
            estado.loss_streak = 0
        else:
            estado.losses += 1
            estado.loss_streak += 1
            estado.win_streak = 0
        
        estado.profit += profit
        estado.total_ops += 1
        
        print(f"[{hora}] {op.simbolo}: {'WIN' if es_win else 'LOSS'} @ ${precio_actual:.5f} | Profit: ${profit:.2f}", flush=True)
        
        estado.operacion_pendiente = None


# ============================================================
#  ALLTICK WEBSOCKET
# ============================================================

class AllTickFeed:
    def __init__(self, simbolos, estados):
        self.simbolos = simbolos
        self.estados = estados
        self.ws = None
        self.url = f"wss://quote.alltick.co/quote-b-ws-api?token={ALLTICK_TOKEN}"
        
    def start(self):
        self.ws = websocket.WebSocketApp(
            self.url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        threading.Thread(target=self.heartbeat, daemon=True).start()
        self.ws.run_forever()
    
    def heartbeat(self):
        while True:
            time.sleep(10)
            if self.ws and self.ws.sock and self.ws.sock.connected:
                hb = {"cmd_id": 22000, "seq_id": 123, "trace": "hb", "data": {}}
                self.ws.send(json.dumps(hb))
    
    def on_open(self, ws):
        print("[OK] Conectado a AllTick", flush=True)
        
        sub_param = {
            "cmd_id": 22002,
            "seq_id": 123,
            "trace": "subscribe",
            "data": {
                "symbol_list": [{"code": f"{sym}.FOREX"} for sym in self.simbolos]
            }
        }
        ws.send(json.dumps(sub_param))
        print(f"[SUSCRITO] {', '.join(self.simbolos)}", flush=True)
    
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            if "data" in data and "symbol_list" in data["data"]:
                for item in data["data"]["symbol_list"]:
                    code = item.get("code", "")
                    price = item.get("last_price", 0)
                    
                    if price <= 0:
                        continue
                    
                    for sym in self.simbolos:
                        if f"{sym}.FOREX" in code:
                            self.procesar_tick(sym, price)
                            break
        except:
            pass
    
    def procesar_tick(self, simbolo, precio):
        estado = self.estados[simbolo]
        estado.tick_count += 1
        hora = datetime.now().strftime("%H:%M:%S")
        
        if estado.tick_count % 10 == 0:
            guardar_tick(simbolo, precio)
        
        verificar_pendientes(estado, precio, hora)
        
        if estado.operacion_pendiente is None:
            decision, razon, confianza = evaluar_senal(estado, precio)
            
            if decision != "NEUTRAL":
                global num_global
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
                print(f"[{hora}] {simbolo}: ENTRADA {decision} @ ${precio:.5f} | {razon}", flush=True)
    
    def on_error(self, ws, error):
        print(f"[ERROR] {error}", flush=True)
    
    def on_close(self, ws, close_status_code, close_msg):
        print(f"[DESCONECTADO] Código: {close_status_code}", flush=True)


# ============================================================
#  MAIN
# ============================================================

num_global = 0

async def main():
    cargar_configuracion()
    
    simbolos = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
    
    estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
    
    print("="*50, flush=True)
    print("  TRADING BOT - ALLTICK FOREX", flush=True)
    print(f"  Activos: {', '.join(simbolos)}", flush=True)
    print(f"  Stake: ${STAKE} | Duración: {DURACION_SEGUNDOS}s", flush=True)
    print("="*50, flush=True)
    
    while True:
        try:
            feed = AllTickFeed(simbolos, estados)
            feed.start()
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    cargar_configuracion()
    asyncio.run(main())
