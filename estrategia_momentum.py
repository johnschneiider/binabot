"""
Estrategia Momentum Breakout con Filtros Adaptativos
Objetivo: Winrate >60% y rentabilidad diaria 10%
"""

from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional
import statistics

@dataclass
class EstadoMomentum:
    """Estado interno de la estrategia de momentum"""
    precios: Deque[float] = None
    retornos: Deque[float] = None
    volatilidad: float = 0.0
    tendencia: float = 0.0
    momentum: float = 0.0
    rsi: float = 50.0
    ema_rapida: Optional[float] = None
    ema_lenta: Optional[float] = None
    ultimo_trade_epoch: int = 0
    racha_perdidas: int = 0
    ultimo_resultado: str = None
    
    def __post_init__(self):
        if self.precios is None:
            self.precios = deque(maxlen=100)
        if self.retornos is None:
            self.retornos = deque(maxlen=50)

def calcular_momentum(precios: Deque[float], ventana: int = 10) -> float:
    """Calcula momentum normalizado"""
    if len(precios) < ventana + 1:
        return 0.0
    
    precio_actual = precios[-1]
    precio_pasado = precios[-(ventana + 1)]
    
    if precio_pasado == 0:
        return 0.0
    
    return (precio_actual - precio_pasado) / precio_pasado

def calcular_volatilidad(precios: Deque[float], ventana: int = 20) -> float:
    """Calcula volatilidad como desviación estándar de retornos"""
    if len(precios) < ventana + 1:
        return 0.0
    
    retornos = []
    for i in range(1, min(ventana, len(precios))):
        if precios[-i-1] != 0:
            ret = (precios[-i] - precios[-i-1]) / precios[-i-1]
            retornos.append(ret)
    
    if len(retornos) < 2:
        return 0.0
    
    return statistics.stdev(retornos) if len(retornos) > 1 else 0.0

def calcular_rsi(precios: Deque[float], periodo: int = 14) -> float:
    """Calcula RSI"""
    if len(precios) < periodo + 1:
        return 50.0
    
    ganancias = []
    perdidas = []
    
    for i in range(1, periodo + 1):
        if precios[-i-1] != 0:
            cambio = (precios[-i] - precios[-i-1]) / precios[-i-1]
            if cambio > 0:
                ganancias.append(cambio)
                perdidas.append(0)
            else:
                ganancias.append(0)
                perdidas.append(abs(cambio))
    
    if len(ganancias) == 0 or len(perdidas) == 0:
        return 50.0
    
    avg_gain = sum(ganancias) / len(ganancias)
    avg_loss = sum(perdidas) / len(perdidas)
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    
    return rsi

def calcular_tendencia(precios: Deque[float], ema_rapida_periodo: int = 9, ema_lenta_periodo: int = 21) -> tuple[float, float]:
    """Calcula EMAs y tendencia"""
    precios_list = list(precios)
    if len(precios_list) < ema_lenta_periodo + 1:
        return 0.0, 0.0
    
    # Calcular EMAs
    alpha_rapida = 2.0 / (ema_rapida_periodo + 1)
    alpha_lenta = 2.0 / (ema_lenta_periodo + 1)
    
    ema_rapida = precios_list[0]
    ema_lenta = precios_list[0]
    
    for precio in precios_list[1:]:
        ema_rapida = alpha_rapida * precio + (1 - alpha_rapida) * ema_rapida
        ema_lenta = alpha_lenta * precio + (1 - alpha_lenta) * ema_lenta
    
    return ema_rapida, ema_lenta

def evaluar_momentum_breakout(
    precio: float,
    estado: EstadoMomentum,
    *,
    momentum_ventana: int = 10,
    volatilidad_ventana: int = 20,
    rsi_periodo: int = 14,
    ema_rapida: int = 9,
    ema_lenta: int = 21,
    umbral_momentum: float = 0.0005,
    umbral_volatilidad: float = 0.001,
    umbral_rsi_sobrecompra: float = 70,
    umbral_rsi_sobreventa: float = 30,
    cooldown_ticks: int = 10,
    stake_base: float = 1.0,
    max_stake: float = 5.0,
    min_ops_dia: int = 10
) -> dict:
    """
    Evalúa la estrategia Momentum Breakout
    
    Returns:
        dict con decision, razon, stake, contract_type, confidence
    """
    
    # Actualizar estado
    estado.precios.append(precio)
    
    if len(estado.precios) < max(momentum_ventana, volatilidad_ventana, rsi_periodo, ema_lenta) + 10:
        return {
            "decision": "NO_OPERAR",
            "razon": "warmup",
            "stake": 0.0,
            "contract_type": None,
            "confidence": 0.0
        }
    
    # Calcular indicadores
    momentum = calcular_momentum(estado.precios, momentum_ventana)
    volatilidad = calcular_volatilidad(estado.precios, volatilidad_ventana)
    rsi = calcular_rsi(estado.precios, rsi_periodo)
    ema_rapida_val, ema_lenta_val = calcular_tendencia(estado.precios, ema_rapida, ema_lenta)
    
    # Determinar tendencia
    if ema_rapida_val > ema_lenta_val:
        tendencia = "ALCISTA"
        contract_type = "CALL"
    elif ema_rapida_val < ema_lenta_val:
        tendencia = "BAJISTA"
        contract_type = "PUT"
    else:
        tendencia = "NEUTRAL"
        contract_type = None
    
    # Filtros
    razones_no_operar = []
    
    # 1. Filtro de momentum
    if abs(momentum) < umbral_momentum:
        razones_no_operar.append(f"momentum_bajo({momentum:.6f})")
    
    # 2. Filtro de volatilidad
    if volatilidad < umbral_volatilidad:
        razones_no_operar.append(f"volatilidad_baja({volatilidad:.6f})")
    
    # 3. Filtro RSI
    if rsi > umbral_rsi_sobrecompra:
        if contract_type == "CALL":
            razones_no_operar.append(f"rsi_sobrecompra({rsi:.1f})")
    elif rsi < umbral_rsi_sobreventa:
        if contract_type == "PUT":
            razones_no_operar.append(f"rsi_sobreventa({rsi:.1f})")
    
    # 4. Filtro de tendencia
    if tendencia == "NEUTRAL":
        razones_no_operar.append("tendencia_neutral")
    
    # 5. Cooldown
    ticks_desde_ultimo = len(estado.precios) - estado.ultimo_trade_epoch
    if ticks_desde_ultimo < cooldown_ticks:
        razones_no_operar.append(f"cooldown({ticks_desde_ultimo}/{cooldown_ticks})")
    
    # 6. Fatiga
    if estado.racha_perdidas >= 3:
        razones_no_operar.append(f"fatiga({estado.racha_perdidas})")
    
    # Decisión
    if razones_no_operar:
        return {
            "decision": "NO_OPERAR",
            "razon": " | ".join(razones_no_operar),
            "stake": 0.0,
            "contract_type": None,
            "confidence": 0.0
        }
    
    # Calcular stake basado en confianza
    confidence = min(1.0, abs(momentum) / umbral_momentum * 0.5 + 
                    volatilidad / umbral_volatilidad * 0.3 + 
                    (1.0 if (rsi > 50 and contract_type == "CALL") or (rsi < 50 and contract_type == "PUT") else 0.5) * 0.2)
    
    stake = min(max_stake, stake_base * (1.0 + confidence))
    
    # Actualizar estado
    estado.ultimo_trade_epoch = len(estado.precios) - 1
    estado.momentum = momentum
    estado.volatilidad = volatilidad
    estado.rsi = rsi
    estado.ema_rapida = ema_rapida_val
    estado.ema_lenta = ema_lenta_val
    
    return {
        "decision": "COMPRA" if contract_type == "CALL" else "VENTA",
        "razon": f"momentum_breakout_{tendencia.lower()}_mom{momentum:.6f}_vol{volatilidad:.6f}_rsi{rsi:.1f}",
        "stake": round(stake, 2),
        "contract_type": contract_type,
        "confidence": round(confidence, 2),
        "indicadores": {
            "momentum": momentum,
            "volatilidad": volatilidad,
            "rsi": rsi,
            "ema_rapida": ema_rapida_val,
            "ema_lenta": ema_lenta_val,
            "tendencia": tendencia
        }
    }

def reportar_resulto(estado: EstadoMomentum, fue_ganancia: bool):
    """Actualiza el estado con el resultado del trade"""
    if fue_ganancia:
        estado.ultimo_resultado = "ganancia"
        estado.racha_perdidas = 0
    else:
        estado.ultimo_resultado = "perdida"
        estado.racha_perdidas += 1
