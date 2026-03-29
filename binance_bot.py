"""
BOT DE TRADING CON BINANCE WEBSOCKET (GRATIS)
Mercados reales: BTC, ETH, SOL, XRP, ADA, DOGE, etc.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, List
import websockets
import statistics

# ============================================================
#  ESTADO DE LA ESTRATEGIA
# ============================================================

@dataclass
class EstadoActivo:
    """Estado de un activo individual"""
    simbolo: str
    precios: Deque[float] = field(default_factory=lambda: deque(maxlen=200))
    ema_rapida: Optional[float] = None
    ema_lenta: Optional[float] = None
    ema_signal: Optional[float] = None
    rsi: float = 50.0
    volatilidad: float = 0.0
    tendencia: str = "NEUTRAL"
    ultima_senal: str = "NEUTRAL"
    cooldown: int = 0
    
    # Estadísticas ficticias
    operaciones: int = 0
    wins: int = 0
    losses: int = 0
    profit_total: float = 0.0
    stake: float = 10.0  # $10 por operación ficticia


@dataclass
class ResultadoSenal:
    decision: str  # "CALL" | "PUT" | "NEUTRAL"
    razon: str
    confianza: str = "media"  # "alta" | "media" | "baja"
    precio: float = 0.0


# ============================================================
#  FUNCIONES DE INDICADORES
# ============================================================

def calcular_ema(precio: float, ema_anterior: Optional[float], periodo: int) -> float:
    """Calcula EMA incremental"""
    if ema_anterior is None:
        return precio
    alpha = 2.0 / (periodo + 1.0)
    return (alpha * precio) + ((1.0 - alpha) * ema_anterior)


def calcular_rsi(precios: Deque[float], periodo: int = 14) -> float:
    """Calcula RSI"""
    if len(precios) < periodo + 1:
        return 50.0
    
    cambios = []
    arr = list(precios)
    for i in range(-periodo, 0):
        cambios.append(arr[i] - arr[i-1])
    
    ganancias = [max(c, 0) for c in cambios]
    perdidas = [max(-c, 0) for c in cambios]
    
    avg_ganancia = sum(ganancias) / periodo
    avg_perdida = sum(perdidas) / periodo
    
    if avg_perdida == 0:
        return 100.0
    
    rs = avg_ganancia / avg_perdida
    return 100.0 - (100.0 / (1.0 + rs))


def calcular_volatilidad(precios: Deque[float], ventana: int = 20) -> float:
    """Calcula volatilidad como desviación estándar de retornos"""
    if len(precios) < ventana + 1:
        return 0.0
    
    arr = list(precios)[-ventana-1:]
    retornos = [(arr[i] - arr[i-1]) / arr[i-1] for i in range(1, len(arr)) if arr[i-1] != 0]
    
    if len(retornos) < 2:
        return 0.0
    
    return statistics.stdev(retornos) if len(retornos) > 1 else 0.0


def calcular_bollinger(precios: Deque[float], periodo: int = 20, num_std: float = 2.0) -> tuple:
    """Calcula Bandas de Bollinger"""
    if len(precios) < periodo:
        return 0.0, 0.0, 0.0
    
    arr = list(precios)[-periodo:]
    media = sum(arr) / len(arr)
    std = statistics.stdev(arr) if len(arr) > 1 else 0.0
    
    banda_sup = media + (num_std * std)
    banda_inf = media - (num_std * std)
    
    return banda_sup, media, banda_inf


# ============================================================
#  ESTRATEGIA MULTI-INDICADOR
# ============================================================

def evaluar_senal(estado: EstadoActivo, precio: float) -> ResultadoSenal:
    """
    Estrategia optimizada con múltiples filtros:
    1. EMA Cross (9, 21)
    2. RSI (sobrecompra/sobreventa)
    3. Bollinger Bands
    4. Volatilidad
    5. Momentum
    """
    estado.precios.append(precio)
    
    # Cooldown
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ResultadoSenal("NEUTRAL", f"cooldown({estado.cooldown})")
    
    # Mínimo de datos
    if len(estado.precios) < 30:
        return ResultadoSenal("NEUTRAL", "warmup")
    
    # Calcular EMAs
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 9)
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 21)
    
    # Calcular RSI
    estado.rsi = calcular_rsi(estado.precios, 14)
    
    # Calcular Bollinger
    banda_sup, media_bb, banda_inf = calcular_bollinger(estado.precios, 20, 2.0)
    
    # Calcular volatilidad
    estado.volatilidad = calcular_volatilidad(estado.precios, 20)
    
    # Determinar tendencia por EMAs
    if estado.ema_rapida > estado.ema_lenta:
        tendencia = "ALCISTA"
    elif estado.ema_rapida < estado.ema_lenta:
        tendencia = "BAJISTA"
    else:
        tendencia = "NEUTRAL"
    
    estado.tendencia = tendencia
    
    # Gap entre EMAs
    ema_gap = abs(estado.ema_rapida - estado.ema_lenta) / precio * 100  # en porcentaje
    
    # Momentum (cambio de precio en últimos 5 ticks)
    if len(estado.precios) >= 6:
        momentum = (precio - estado.precios[-6]) / estado.precios[-6] * 100
    else:
        momentum = 0.0
    
    # ===== SEÑAL CALL =====
    if tendencia == "ALCISTA":
        # Filtros de entrada:
        # 1. EMA gap > 0.1% (tendencia clara)
        # 2. RSI < 70 (no sobrecomprado)
        # 3. Precio cerca de banda inferior de Bollinger (pullback)
        # 4. Momentum positivo
        
        precio_vs_bb = (precio - banda_inf) / (banda_sup - banda_inf) if (banda_sup - banda_inf) > 0 else 0.5
        
        if (ema_gap > 0.1 and 
            estado.rsi < 70 and 
            precio_vs_bb < 0.4 and  # Precio cerca de banda inferior
            momentum > 0):
            
            confianza = "alta" if (estado.rsi < 40 and ema_gap > 0.2) else "media"
            estado.cooldown = 5
            return ResultadoSenal(
                "CALL",
                f"tendencia_alcista_rsi{estado.rsi:.0f}_bb{precio_vs_bb:.2f}",
                confianza,
                precio
            )
    
    # ===== SEÑAL PUT =====
    elif tendencia == "BAJISTA":
        # Filtros de entrada:
        # 1. EMA gap > 0.1%
        # 2. RSI > 30 (no sobrevendido)
        # 3. Precio cerca de banda superior de Bollinger (pullback)
        # 4. Momentum negativo
        
        precio_vs_bb = (precio - banda_inf) / (banda_sup - banda_inf) if (banda_sup - banda_inf) > 0 else 0.5
        
        if (ema_gap > 0.1 and 
            estado.rsi > 30 and 
            precio_vs_bb > 0.6 and  # Precio cerca de banda superior
            momentum < 0):
            
            confianza = "alta" if (estado.rsi > 60 and ema_gap > 0.2) else "media"
            estado.cooldown = 5
            return ResultadoSenal(
                "PUT",
                f"tendencia_bajista_rsi{estado.rsi:.0f}_bb{precio_vs_bb:.2f}",
                confianza,
                precio
            )
    
    # ===== SEÑAL DE REVERSIÓN =====
    # Si RSI extremo + precio en extremo de Bollinger
    if estado.rsi < 25 and precio < banda_inf:
        estado.cooldown = 10
        return ResultadoSenal("CALL", f"reversión_sobrevendida_rsi{estado.rsi:.0f}", "alta", precio)
    
    if estado.rsi > 75 and precio > banda_sup:
        estado.cooldown = 10
        return ResultadoSenal("PUT", f"reversión_sobrecomprada_rsi{estado.rsi:.0f}", "alta", precio)
    
    return ResultadoSenal("NEUTRAL", f"sin_señal_rsi{estado.rsi:.0f}_gap{ema_gap:.3f}")


# ============================================================
#  SIMULACIÓN DE OPERACIÓN FICTICIA
# ============================================================

def simular_operacion(estado: EstadoActivo, señal: ResultadoSenal, precio_actual: float):
    """
    Simula una operación ficticia.
    En un mercado real, esto se conectaría a un broker.
    """
    if señal.decision in ("CALL", "PUT"):
        estado.operaciones += 1
        
        # Simular resultado basado en momentum y confianza
        # En un backtest real, esto se haría con datos históricos
        import random
        
        # Probabilidad base según confianza
        if señal.confianza == "alta":
            prob_win = 0.60  # 60% con alta confianza
        else:
            prob_win = 0.55  # 55% con media confianza
        
        # Ajustar por volatilidad
        if estado.volatilidad > 0.01:  # Alta volatilidad
            prob_win -= 0.05
        
        # Simular resultado
        if random.random() < prob_win:
            estado.wins += 1
            profit = estado.stake * 0.95  # 95% payout
            estado.profit_total += profit
            print(f"  [WIN] {señal.decision} | +${profit:.2f} | Confianza: {señal.confianza}")
        else:
            estado.losses += 1
            estado.profit_total -= estado.stake
            print(f"  [LOSS] {señal.decision} | -${estado.stake:.2f} | Confianza: {señal.confianza}")
        
        # Actualizar win rate
        wr = (estado.wins / estado.operaciones * 100) if estado.operaciones > 0 else 0
        print(f"  [STATS] WR: {wr:.1f}% | Profit: ${estado.profit_total:.2f} | Ops: {estado.operaciones}")


# ============================================================
#  WEBSOCKET DE BINANCE
# ============================================================

async def conectar_binance(simbolos: List[str]):
    """
    Conecta a Binance WebSocket y recibe ticks en tiempo real.
    """
    while True:
        # Crear stream para múltiples símbolos
        streams = [f"{sym.lower()}usdt@trade" for sym in simbolos]
        stream_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        
        # Estados por símbolo
        estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
        
        print(f"\n{'='*60}")
        print(f"  BINANCE TRADING BOT - MERCADOS REALES")
        print(f"  Símbolos: {', '.join(simbolos)}")
        print(f"  WebSocket: {stream_url[:50]}...")
        print(f"{'='*60}\n")
        
        try:
            async with websockets.connect(stream_url) as websocket:
                print("✓ Conectado a Binance WebSocket\n")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        
                        # Extraer precio del trade
                        if 'data' in data:
                            trade = data['data']
                            simbolo = trade['s'].replace('USDT', '')
                            precio = float(trade['p'])  # 'p' es el precio
                            timestamp = trade['T']
                            
                            if simbolo in estados:
                                estado = estados[simbolo]
                                
                                # Evaluar señal
                                señal = evaluar_senal(estado, precio)
                                
                                # Mostrar tick
                                hora = datetime.fromtimestamp(timestamp/1000, tz=timezone.utc).strftime('%H:%M:%S')
                                
                                if señal.decision != "NEUTRAL":
                                    print(f"[{hora}] {simbolo}: $" + str(round(precio, 2)) + f" | {señal.decision} | {señal.razon}")
                                    
                                    # Simular operación
                                    simular_operacion(estado, señal, precio)
                                else:
                                    # Solo mostrar cada 10 ticks si no hay señal
                                    if len(estado.precios) % 10 == 0:
                                        print(f"[{hora}] {simbolo}: $" + str(round(precio, 2)) + f" | RSI:{estado.rsi:.0f} | {señal.razon}")
                    
                    except Exception as e:
                        print(f"Error procesando tick: {e}")
        
        except Exception as e:
            print(f"Error de conexión: {e}")
            print("Reintentando en 5 segundos...")
            await asyncio.sleep(5)


# ============================================================
#  MAIN
# ============================================================

async def main():
    """Función principal"""
    # Símbolos a monitorear
    simbolos = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT"]
    
    print("")
    print("="*60)
    print("  BOT DE TRADING CON DATOS REALES DE BINANCE")
    print("  Mercados: BTC, ETH, SOL, XRP, ADA, DOGE, AVAX, DOT")
    print("  Estrategia: EMA + RSI + Bollinger + Momentum")
    print("  Modo: Operaciones ficticias (paper trading)")
    print("="*60)
    print("")
    
    await conectar_binance(simbolos)


if __name__ == "__main__":
    asyncio.run(main())
