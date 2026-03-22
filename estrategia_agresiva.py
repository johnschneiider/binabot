"""
Estrategia Simplificada de Momentum + Soporte/Resistencia
Versión agresiva para lograr 10% diario
"""

from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional
import statistics

@dataclass
class EstadoAgresivo:
    precios: Deque[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    rsi: float = 50.0
    volatilidad: float = 0.0
    momentum: float = 0.0
    ultimo_trade: int = 0
    racha_perdidas: int = 0
    
    def __post_init__(self):
        if self.precios is None:
            self.precios = deque(maxlen=100)

def evaluar_momentum_agresivo(
    precio: float,
    estado: EstadoAgresivo,
    *,
    ema_fast_period: int = 9,
    ema_slow_period: int = 21,
    rsi_periodo: int = 14,
    cooldown: int = 2
) -> dict:
    """
    Estrategia agresiva de momentum
    Objetivo: Muchas señales, winrate >55%
    """
    estado.precios.append(precio)
    
    if len(estado.precios) < max(ema_slow_period, rsi_periodo) + 5:
        return {"decision": "NO_OPERAR", "razon": "warmup", "stake": 0.0, "tipo": None}
    
    # Actualizar EMAs
    alpha_fast = 2.0 / (ema_fast_period + 1)
    alpha_slow = 2.0 / (ema_slow_period + 1)
    
    if estado.ema_fast is None:
        estado.ema_fast = precio
        estado.ema_slow = precio
    else:
        estado.ema_fast = alpha_fast * precio + (1 - alpha_fast) * estado.ema_fast
        estado.ema_slow = alpha_slow * precio + (1 - alpha_slow) * estado.ema_slow
    
    # Calcular RSI
    if len(estado.precios) >= rsi_periodo + 1:
        gains = []
        losses = []
        precios_list = list(estado.precios)
        
        for i in range(1, len(precios_list)):
            cambio = precios_list[i] - precios_list[i-1]
            if cambio > 0:
                gains.append(cambio)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(cambio))
        
        avg_gain = sum(gains[-rsi_periodo:]) / rsi_periodo
        avg_loss = sum(losses[-rsi_periodo:]) / rsi_periodo
        
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            estado.rsi = 100.0 - (100.0 / (1.0 + rs))
    
    # Calcular momentum (cambio porcentual reciente)
    if len(estado.precios) >= 5:
        estado.momentum = (precio - estado.precios[-5]) / estado.precios[-5] if estado.precios[-5] != 0 else 0
    
    # Calcular volatilidad
    if len(estado.precios) >= 20:
        precios_list = list(estado.precios)[-20:]
        retornos = [(precios_list[i] - precios_list[i-1]) / precios_list[i-1] 
                    for i in range(1, len(precios_list)) if precios_list[i-1] != 0]
        if len(retornos) > 1:
            estado.volatilidad = statistics.stdev(retornos)
    
    # Cooldown
    ticks_desde_ultimo = len(estado.precios) - estado.ultimo_trade
    if ticks_desde_ultimo < cooldown:
        return {"decision": "NO_OPERAR", "razon": f"cooldown({ticks_desde_ultimo}/{cooldown})", "stake": 0.0, "tipo": None}
    
    # Lógica de señal
    tendencia_alcista = estado.ema_fast > estado.ema_slow
    tendencia_bajista = estado.ema_fast < estado.ema_slow
    
    # Señales agresivas
    if tendencia_alcista and estado.rsi < 40 and estado.momentum > 0:
        # CALL: tendencia alcista + RSI bajo + momentum positivo
        stake = 1.0
        estado.ultimo_trade = len(estado.precios) - 1
        return {
            "decision": "COMPRA",
            "razon": f"call_tendencia_alcista_rsi{estado.rsi:.1f}_mom{estado.momentum:.6f}",
            "stake": stake,
            "tipo": "CALL",
            "confidence": 0.7
        }
    
    elif tendencia_bajista and estado.rsi > 60 and estado.momentum < 0:
        # PUT: tendencia bajista + RSI alto + momentum negativo
        stake = 1.0
        estado.ultimo_trade = len(estado.precios) - 1
        return {
            "decision": "VENTA",
            "razon": f"put_tendencia_bajista_rsi{estado.rsi:.1f}_mom{estado.momentum:.6f}",
            "stake": stake,
            "tipo": "PUT",
            "confidence": 0.7
        }
    
    # Señales adicionales para más oportunidades
    elif abs(estado.momentum) > 0.0001 and estado.volatilidad > 0.00005:
        # Momentum fuerte con volatilidad
        if estado.momentum > 0 and estado.rsi < 55:
            stake = 0.75
            estado.ultimo_trade = len(estado.precios) - 1
            return {
                "decision": "COMPRA",
                "razon": f"momentum_positivo_rsi{estado.rsi:.1f}_mom{estado.momentum:.6f}",
                "stake": stake,
                "tipo": "CALL",
                "confidence": 0.5
            }
        elif estado.momentum < 0 and estado.rsi > 45:
            stake = 0.75
            estado.ultimo_trade = len(estado.precios) - 1
            return {
                "decision": "VENTA",
                "razon": f"momentum_negativo_rsi{estado.rsi:.1f}_mom{estado.momentum:.6f}",
                "stake": stake,
                "tipo": "PUT",
                "confidence": 0.5
            }
    
    return {"decision": "NO_OPERAR", "razon": "sin_senal", "stake": 0.0, "tipo": None}

def reportar_resulto_agresivo(estado: EstadoAgresivo, fue_ganancia: bool):
    if fue_ganancia:
        estado.racha_perdidas = 0
    else:
        estado.racha_perdidas += 1