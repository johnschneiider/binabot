"""
BOT BINANCE - OPERACIONES DE 60 SEGUNDOS
Versión corregida con logs visibles
"""

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

DJANGO_API_URL = "http://127.0.0.1:8000/api/binance/guardar/"
DJANGO_TICK_URL = "http://127.0.0.1:8000/api/binance/tick/"

STAKE = 1.0
PAYOUT = 0.95
DURACION_SEGUNDOS = 60
COOLDOWN_TICKS = 150  # ~3-5 minutos entre operaciones


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
    
    if ema_gap < 0.2:
        return ("NEUTRAL", "gap_bajo", "baja")
    if estado.adx < 20:
        return ("NEUTRAL", "adx_bajo", "baja")
    if estado.rsi < 30 or estado.rsi > 70:
        return ("NEUTRAL", "rsi_extremo", "baja")
    if not (triple_alcista or triple_bajista):
        return ("NEUTRAL", "no_triple", "baja")
    if precio_vs_bb < 0.2 or precio_vs_bb > 0.8:
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
    
    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
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
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    
    while True:
        try:
            print("[CONECTANDO] Binance...", flush=True)
            await conectar_binance(simbolos)
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[DESCONECTADO] {e}", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
