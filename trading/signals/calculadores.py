"""
Calculadores de indicadores técnicos para análisis de trading.
"""
import statistics
from decimal import Decimal
from typing import List, Tuple

from django.db.models import QuerySet


def calcular_momentum(precios: List[Decimal], periodo: int = 10) -> Tuple[Decimal, Decimal]:
    """
    Calcula momentum simple y porcentual.
    
    Args:
        precios: Lista de precios ordenados (más reciente al final)
        periodo: Número de ticks a considerar
    
    Returns:
        Tuple[momentum_simple, momentum_pct]
    """
    if len(precios) < periodo:
        return Decimal("0.00"), Decimal("0.00")
    
    precios_periodo = precios[-periodo:]
    precio_inicial = precios_periodo[0]
    precio_final = precios_periodo[-1]
    
    momentum_simple = precio_final - precio_inicial
    momentum_pct = (momentum_simple / precio_inicial * Decimal("100")).quantize(
        Decimal("0.0001")
    )
    
    return momentum_simple, momentum_pct


def calcular_volatilidad(precios: List[Decimal], periodo: int = 20) -> Decimal:
    """
    Calcula la desviación estándar (volatilidad) de los últimos N ticks.
    
    Args:
        precios: Lista de precios ordenados
        periodo: Número de ticks a considerar
    
    Returns:
        Volatilidad (desviación estándar)
    """
    if len(precios) < 2:
        return Decimal("0.00")
    
    precios_periodo = precios[-periodo:] if len(precios) >= periodo else precios
    
    # Convertir a float para cálculo estadístico
    precios_float = [float(p) for p in precios_periodo]
    
    if len(precios_float) < 2:
        return Decimal("0.00")
    
    try:
        desviacion = statistics.stdev(precios_float)
        return Decimal(str(desviacion)).quantize(Decimal("0.0001"))
    except statistics.StatisticsError:
        return Decimal("0.00")


def calcular_ema(precios: List[Decimal], periodo: int = 10) -> Decimal:
    """
    Calcula la Media Móvil Exponencial (EMA) de los últimos N ticks.
    
    Args:
        precios: Lista de precios ordenados
        periodo: Período de la EMA
    
    Returns:
        Valor de la EMA
    """
    if not precios:
        return Decimal("0.00")
    
    precios_periodo = precios[-periodo:] if len(precios) >= periodo else precios
    
    if len(precios_periodo) == 1:
        return precios_periodo[0]
    
    # Calcular SMA inicial
    sma = sum(precios_periodo[:periodo]) / Decimal(str(len(precios_periodo[:periodo])))
    
    # Calcular multiplicador
    multiplicador = Decimal("2") / Decimal(str(periodo + 1))
    
    # Calcular EMA iterativamente
    ema = sma
    for precio in precios_periodo[periodo:]:
        ema = (precio - ema) * multiplicador + ema
    
    return ema.quantize(Decimal("0.00001"))


def calcular_rate_of_change(precios: List[Decimal], periodo: int = 10) -> Decimal:
    """
    Calcula la pendiente de una regresión lineal simple (Rate of Change).
    
    Args:
        precios: Lista de precios ordenados
        periodo: Número de ticks a considerar
    
    Returns:
        Pendiente de la regresión (ROC)
    """
    if len(precios) < periodo:
        return Decimal("0.00")
    
    precios_periodo = precios[-periodo:]
    
    # Regresión lineal simple: y = mx + b
    n = len(precios_periodo)
    x_sum = sum(range(n))
    y_sum = sum(precios_periodo)
    xy_sum = sum(i * float(precio) for i, precio in enumerate(precios_periodo))
    x2_sum = sum(i * i for i in range(n))
    
    # Calcular pendiente (m)
    denominador = Decimal(str(n * x2_sum - x_sum * x_sum))
    if denominador == 0:
        return Decimal("0.00")
    
    numerador = Decimal(str(n * xy_sum - x_sum * y_sum))
    pendiente = numerador / denominador
    
    return pendiente.quantize(Decimal("0.0001"))


def calcular_fuerza_movimiento(
    precio_actual: Decimal, ema: Decimal
) -> Decimal:
    """
    Calcula la fuerza del movimiento: |EMA - precio_actual|
    
    Args:
        precio_actual: Precio actual del activo
        ema: Valor de la EMA
    
    Returns:
        Fuerza del movimiento (valor absoluto de la diferencia)
    """
    fuerza = abs(ema - precio_actual)
    return fuerza.quantize(Decimal("0.00001"))


def calcular_consistencia(precios: List[Decimal], periodo: int = 10) -> Decimal:
    """
    Calcula el porcentaje de ticks consecutivos en la misma dirección.
    
    Args:
        precios: Lista de precios ordenados
        periodo: Número de ticks a analizar
    
    Returns:
        Porcentaje de consistencia (0-100)
    """
    if len(precios) < 2:
        return Decimal("0.00")
    
    precios_periodo = precios[-periodo:] if len(precios) >= periodo else precios
    
    if len(precios_periodo) < 2:
        return Decimal("0.00")
    
    direcciones = []
    for i in range(1, len(precios_periodo)):
        if precios_periodo[i] > precios_periodo[i - 1]:
            direcciones.append(1)  # Subida
        elif precios_periodo[i] < precios_periodo[i - 1]:
            direcciones.append(-1)  # Bajada
        else:
            direcciones.append(0)  # Sin cambio
    
    if not direcciones:
        return Decimal("0.00")
    
    # Contar direcciones consistentes
    direccion_inicial = direcciones[0]
    if direccion_inicial == 0:
        return Decimal("0.00")
    
    consistentes = 1  # El primer movimiento cuenta
    for direccion in direcciones[1:]:
        if direccion == direccion_inicial:
            consistentes += 1
        else:
            break  # Se rompe la consistencia
    
    porcentaje = (Decimal(str(consistentes)) / Decimal(str(len(direcciones))) * Decimal("100")).quantize(
        Decimal("0.01")
    )
    
    return porcentaje

