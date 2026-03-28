"""
BOT BINANCE CON INTEGRACION DJANGO
Guarda operaciones en la base de datos via API
"""

import asyncio
import json
import time
import sys
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional
import websockets
import statistics
import urllib.request
import urllib.error

# ============================================================
#  CONFIGURACION
# ============================================================

DJANGO_API_URL = "http://127.0.0.1:8000/api/binance/guardar/"
DJANGO_ESTADO_URL = "http://127.0.0.1:8000/api/estado_binance/"

STAKE = 10.0  # $10 por operación ficticia
PAYOUT = 0.95  # 95% de payout

# Probabilidad de win según confianza
PROB_WIN_ALTA = 0.65
PROB_WIN_MEDIA = 0.55
PROB_WIN_BAJA = 0.50


# ============================================================
#  INDICADORES
# ============================================================

def calcular_ema(precio: float, ema_anterior: Optional[float], periodo: int) -> float:
    if ema_anterior is None:
        return precio
    alpha = 2.0 / (periodo + 1.0)
    return (alpha * precio) + ((1.0 - alpha) * ema_anterior)


def calcular_rsi(precios: list, periodo: int = 14) -> float:
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


def calcular_bollinger(precios: list, periodo: int = 20, num_std: float = 2.0) -> tuple:
    if len(precios) < periodo:
        return 0.0, 0.0, 0.0
    arr = precios[-periodo:]
    media = sum(arr) / len(arr)
    std = statistics.stdev(arr) if len(arr) > 1 else 0.0
    return media + (num_std * std), media, media - (num_std * std)


def calcular_volatilidad(precios: list, ventana: int = 20) -> float:
    if len(precios) < ventana + 1:
        return 0.0
    arr = precios[-ventana-1:]
    retornos = [(arr[i] - arr[i-1]) / arr[i-1] for i in range(1, len(arr)) if arr[i-1] != 0]
    return statistics.stdev(retornos) if len(retornos) > 1 else 0.0


# ============================================================
#  ESTADO DEL ACTIVO
# ============================================================

@dataclass
class EstadoActivo:
    simbolo: str
    precios: list = field(default_factory=lambda: [])
    ema_rapida: Optional[float] = None
    ema_lenta: Optional[float] = None
    rsi: float = 50.0
    volatilidad: float = 0.0
    cooldown: int = 0
    total_ops: int = 0
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0


# ============================================================
#  ESTRATEGIA
# ============================================================

def evaluar_senal(estado: EstadoActivo, precio: float) -> tuple:
    """Retorna (decision, razon, confianza)"""
    estado.precios.append(precio)
    
    # Mantener solo últimos 200 precios
    if len(estado.precios) > 200:
        estado.precios = estado.precios[-200:]
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cooldown({estado.cooldown})", "media")
    
    if len(estado.precios) < 30:
        return ("NEUTRAL", "warmup", "baja")
    
    # Calcular indicadores
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 9)
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 21)
    estado.rsi = calcular_rsi(estado.precios, 14)
    banda_sup, media_bb, banda_inf = calcular_bollinger(estado.precios, 20, 2.0)
    estado.volatilidad = calcular_volatilidad(estado.precios, 20)
    
    # Tendencia
    ema_gap = abs(estado.ema_rapida - estado.ema_lenta) / precio * 100
    tendencia = "ALCISTA" if estado.ema_rapida > estado.ema_lenta else "BAJISTA"
    
    # Momentum
    momentum = 0.0
    if len(estado.precios) >= 6:
        momentum = (precio - estado.precios[-6]) / estado.precios[-6] * 100
    
    # Posición en Bollinger
    precio_vs_bb = 0.5
    if (banda_sup - banda_inf) > 0:
        precio_vs_bb = (precio - banda_inf) / (banda_sup - banda_inf)
    
    # ===== SEÑALES =====
    
    # 1. REVERSIÓN EN EXTREMOS (mayor confianza)
    if estado.rsi < 25 and precio < banda_inf:
        estado.cooldown = 5
        return ("CALL", f"reversión_sobrevendida_rsi{estado.rsi:.0f}", "alta")
    
    if estado.rsi > 75 and precio > banda_sup:
        estado.cooldown = 5
        return ("PUT", f"reversión_sobrecomprada_rsi{estado.rsi:.0f}", "alta")
    
    # 2. TEN + PULLBACK (confianza media)
    if tendencia == "ALCISTA" and ema_gap > 0.15:
        if precio_vs_bb < 0.35 and momentum > 0 and estado.rsi < 65:
            estado.cooldown = 3
            return ("CALL", f"pullback_alcista_rsi{estado.rsi:.0f}", "media")
    
    if tendencia == "BAJISTA" and ema_gap > 0.15:
        if precio_vs_bb > 0.65 and momentum < 0 and estado.rsi > 35:
            estado.cooldown = 3
            return ("PUT", f"pullback_bajista_rsi{estado.rsi:.0f}", "media")
    
    # 3. MOMENTUM FUERTE
    if abs(momentum) > 0.5:
        if momentum > 0 and estado.rsi < 70 and ema_gap > 0.1:
            estado.cooldown = 3
            return ("CALL", f"momentum_alcista{momentum:.2f}", "media")
        if momentum < 0 and estado.rsi > 30 and ema_gap > 0.1:
            estado.cooldown = 3
            return ("PUT", f"momentum_bajista{momentum:.2f}", "media")
    
    return ("NEUTRAL", f"sin_señal_rsi{estado.rsi:.0f}", "baja")


# ============================================================
#  GUARDAR OPERACION EN DJANGO
# ============================================================

def guardar_operacion(simbolo: str, direccion: str, precio: float, 
                      razon: str, confianza: str, es_win: bool, profit: float):
    """Guarda la operación en Django via API"""
    import random
    
    data = {
        "simbolo": simbolo,
        "direccion": direccion,
        "precio_entrada": precio,
        "razon": razon,
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
        result = json.loads(response.read())
        return result
    except Exception as e:
        print(f"Error guardando operación: {e}")
        return None


# ============================================================
#  SIMULAR OPERACIÓN
# ============================================================

def simular_operacion(estado: EstadoActivo, decision: str, confianza: str, razon: str, precio: float):
    """Simula operación ficticia"""
    import random
    
    # Probabilidad según confianza
    if confianza == "alta":
        prob_win = PROB_WIN_ALTA
    elif confianza == "media":
        prob_win = PROB_WIN_MEDIA
    else:
        prob_win = PROB_WIN_BAJA
    
    # Ajustar por volatilidad
    if estado.volatilidad > 0.01:
        prob_win -= 0.05
    
    # Simular resultado
    es_win = random.random() < prob_win
    
    if es_win:
        profit = STAKE * PAYOUT  # $9.50
        estado.wins += 1
        estado.win_streak += 1
        estado.loss_streak = 0
    else:
        profit = -STAKE  # -$10.00
        estado.losses += 1
        estado.loss_streak += 1
        estado.win_streak = 0
    
    estado.total_ops += 1
    estado.profit += profit
    
    # Guardar en Django
    resultado = guardar_operacion(simbolo, decision, precio, razon, confianza, es_win, profit)
    
    wr = (estado.wins / estado.total_ops * 100) if estado.total_ops > 0 else 0
    
    return es_win, profit, wr


# ============================================================
#  WEBSOCKET BINANCE
# ============================================================

async def conectar_binance(simbolos: list):
    """Conecta a Binance WebSocket"""
    
    streams = [f"{sym.lower()}usdt@trade" for sym in simbolos]
    url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
    
    estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
    
    print("="*60)
    print("  BINANCE BOT - INTEGRADO CON DJANGO")
    print(f"  Activos: {', '.join(simbolos)}")
    print(f"  Stake: ${STAKE} | Payout: {PAYOUT*100}%")
    print("="*60)
    print()
    
    async with websockets.connect(url) as ws:
        print("[OK] Conectado a Binance WebSocket")
        print()
        
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
                
                # Evaluar señal
                decision, razon, confianza = evaluar_senal(estado, precio)
                
                if decision != "NEUTRAL":
                    # Simular operación
                    es_win, profit, wr = simular_operacion(estado, decision, razon, confianza, precio)
                    
                    # Mostrar resultado
                    resultado = "WIN" if es_win else "LOSS"
                    print(f"[{hora}] {simbolo}: $" + str(round(precio, 2)) + 
                          f" | {decision} | {resultado} ({profit:+.2f}) | " +
                          f"WR:{wr:.1f}% | Ops:{estado.total_ops}")
                
            except Exception as e:
                print(f"Error: {e}")


# ============================================================
#  MAIN
# ============================================================

async def main():
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    await conectar_binance(simbolos)


if __name__ == "__main__":
    asyncio.run(main())
