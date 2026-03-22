"""
Estrategia Mejorada - Momentum + Filtros Inteligentes
"""

from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional
import statistics

@dataclass
class EstadoMejorado:
    precios: Deque[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    ema_signal: Optional[float] = None  # Tercera EMA para confirmación
    rsi: float = 50.0
    volatilidad: float = 0.0
    momentum: float = 0.0
    ultimo_trade: int = 0
    racha_perdidas: int = 0
    hist_precios: Deque[float] = None  # Para detectar tendencia
    
    def __post_init__(self):
        if self.precios is None:
            self.precios = deque(maxlen=150)
        if self.hist_precios is None:
            self.hist_precios = deque(maxlen=30)

def es_mercado_lateral(precios: Deque[float], ventana: int = 30, umbral: float = 0.0002) -> bool:
    """Detecta si el mercado está en rango lateral"""
    if len(precios) < ventana:
        return False
    
    precios_list = list(precios)[-ventana:]
    max_p = max(precios_list)
    min_p = min(precios_list)
    
    if max_p == 0:
        return False
    
    rango_pct = (max_p - min_p) / max_p
    return rango_pct < umbral

def evaluar_estrategia_mejorada(
    precio: float,
    estado: EstadoMejorado,
    *,
    ema_fast_period: int = 8,
    ema_slow_period: int = 21,
    ema_signal_period: int = 50,
    rsi_periodo: int = 14,
    cooldown: int = 4
) -> dict:
    """
    Estrategia mejorada con múltiples confirmaciones
    Objetivo: Winrate >60%
    """
    estado.precios.append(precio)
    estado.hist_precios.append(precio)
    
    if len(estado.precios) < max(ema_signal_period, rsi_periodo) + 10:
        return {"decision": "NO_OPERAR", "razon": "warmup", "stake": 0.0, "tipo": None}
    
    # Actualizar EMAs
    alpha_fast = 2.0 / (ema_fast_period + 1)
    alpha_slow = 2.0 / (ema_slow_period + 1)
    alpha_signal = 2.0 / (ema_signal_period + 1)
    
    if estado.ema_fast is None:
        estado.ema_fast = precio
        estado.ema_slow = precio
        estado.ema_signal = precio
    else:
        estado.ema_fast = alpha_fast * precio + (1 - alpha_fast) * estado.ema_fast
        estado.ema_slow = alpha_slow * precio + (1 - alpha_slow) * estado.ema_slow
        estado.ema_signal = alpha_signal * precio + (1 - alpha_signal) * estado.ema_signal
    
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
    
    # Calcular momentum
    if len(estado.precios) >= 8:
        estado.momentum = (precio - estado.precios[-8]) / estado.precios[-8] if estado.precios[-8] != 0 else 0
    
    # Calcular volatilidad
    if len(estado.precios) >= 20:
        precios_list = list(estado.precios)[-20:]
        retornos = [(precios_list[i] - precios_list[i-1]) / precios_list[i-1] 
                    for i in range(1, len(precios_list)) if precios_list[i-1] != 0]
        if len(retornos) > 1:
            estado.volatilidad = statistics.stdev(retornos)
    
    # Filtros
    # 1. Mercado lateral
    if es_mercado_lateral(estado.hist_precios, ventana=30, umbral=0.0002):
        return {"decision": "NO_OPERAR", "razon": "mercado_lateral", "stake": 0.0, "tipo": None}
    
    # 2. Cooldown
    ticks_desde_ultimo = len(estado.precios) - estado.ultimo_trade
    if ticks_desde_ultimo < cooldown:
        return {"decision": "NO_OPERAR", "razon": f"cooldown", "stake": 0.0, "tipo": None}
    
    # 3. Fatiga
    if estado.racha_perdidas >= 2:
        return {"decision": "NO_OPERAR", "razon": "fatiga", "stake": 0.0, "tipo": None}
    
    # 4. Volatilidad muy baja
    if estado.volatilidad < 0.00003:
        return {"decision": "NO_OPERAR", "razon": "vol_baja", "stake": 0.0, "tipo": None}
    
    # Lógica de entrada mejorada
    tendencia_alcista = estado.ema_fast > estado.ema_slow and estado.ema_slow > estado.ema_signal
    tendencia_bajista = estado.ema_fast < estado.ema_slow and estado.ema_slow < estado.ema_signal
    
    # Señal fuerte: triple confirmación
    if tendencia_alcista:
        # RSI en zona de compra (<50 pero no sobreventa extrema)
        # Momentum positivo
        # Precio por encima de EMA rápida
        if estado.rsi < 50 and estado.rsi > 30 and estado.momentum > 0 and precio > estado.ema_fast:
            stake = 1.0
            estado.ultimo_trade = len(estado.precios) - 1
            return {
                "decision": "COMPRA",
                "razon": f"call_alcista_rsi{estado.rsi:.1f}_mom{estado.momentum:.6f}",
                "stake": stake,
                "tipo": "CALL",
                "confidence": 0.8
            }
    
    elif tendencia_bajista:
        # RSI en zona de venta (>50 pero no sobrecompra extrema)
        # Momentum negativo
        # Precio por debajo de EMA rápida
        if estado.rsi > 50 and estado.rsi < 70 and estado.momentum < 0 and precio < estado.ema_fast:
            stake = 1.0
            estado.ultimo_trade = len(estado.precios) - 1
            return {
                "decision": "VENTA",
                "razon": f"put_bajista_rsi{estado.rsi:.1f}_mom{estado.momentum:.6f}",
                "stake": stake,
                "tipo": "PUT",
                "confidence": 0.8
            }
    
    # Señal de rebote (menos frecuente pero más segura)
    if tendencia_alcista and estado.rsi < 35 and estado.momentum > 0:
        # Rebote en tendencia alcista
        stake = 0.8
        estado.ultimo_trade = len(estado.precios) - 1
        return {
            "decision": "COMPRA",
            "razon": f"rebote_alcista_rsi{estado.rsi:.1f}",
            "stake": stake,
            "tipo": "CALL",
            "confidence": 0.7
        }
    
    elif tendencia_bajista and estado.rsi > 65 and estado.momentum < 0:
        # Rebote en tendencia bajista
        stake = 0.8
        estado.ultimo_trade = len(estado.precios) - 1
        return {
            "decision": "VENTA",
            "razon": f"rebote_bajista_rsi{estado.rsi:.1f}",
            "stake": stake,
            "tipo": "PUT",
            "confidence": 0.7
        }
    
    return {"decision": "NO_OPERAR", "razon": "sin_senal", "stake": 0.0, "tipo": None}

def reportar_resulto_mejorado(estado: EstadoMejorado, fue_ganancia: bool):
    if fue_ganancia:
        estado.racha_perdidas = 0
    else:
        estado.racha_perdidas += 1