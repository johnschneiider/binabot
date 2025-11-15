"""
Sistema de scoring profesional para ranking de activos.
"""
from decimal import Decimal
from typing import Dict, Optional

from trading.models import IndicadoresActivo, RendimientoActivo


class PesosScoring:
    """Pesos estándar para el cálculo de score."""
    
    MOMENTUM = Decimal("0.30")
    ROC = Decimal("0.20")
    TENDENCIA_EMA = Decimal("0.20")
    VOLATILIDAD = Decimal("0.10")
    CONSISTENCIA = Decimal("0.10")
    HISTORIAL = Decimal("0.10")
    
    # Verificar que sumen 1.0
    @classmethod
    def verificar(cls) -> bool:
        total = (
            cls.MOMENTUM
            + cls.ROC
            + cls.TENDENCIA_EMA
            + cls.VOLATILIDAD
            + cls.CONSISTENCIA
            + cls.HISTORIAL
        )
        return total == Decimal("1.00")


def normalizar_valor(
    valor: Decimal, min_valor: Decimal, max_valor: Decimal
) -> Decimal:
    """
    Normaliza un valor al rango 0-100.
    
    Args:
        valor: Valor a normalizar
        min_valor: Valor mínimo esperado
        max_valor: Valor máximo esperado
    
    Returns:
        Valor normalizado (0-100)
    """
    if max_valor == min_valor:
        return Decimal("50.00")  # Valor medio si no hay rango
    
    if valor < min_valor:
        return Decimal("0.00")
    if valor > max_valor:
        return Decimal("100.00")
    
    normalizado = ((valor - min_valor) / (max_valor - min_valor)) * Decimal("100")
    return normalizado.quantize(Decimal("0.01"))


def calcular_score_activo(
    indicadores: IndicadoresActivo,
    rendimiento: Optional[RendimientoActivo] = None,
    umbral_minimo: Decimal = Decimal("30.00"),
) -> Decimal:
    """
    Calcula el score total (0-100) para un activo.
    
    Fórmula:
    score = (
        ws_momentum * momentum_pct_normalizado
      + ws_roc * roc_normalizado
      + ws_vol * volatilidad_normalizada
      + ws_tendencia * tendencia_normalizada
      + ws_consistencia * consistencia
      + ws_historial * winrate_historico
    )
    
    Args:
        indicadores: Indicadores técnicos del activo
        rendimiento: Rendimiento histórico (opcional)
        umbral_minimo: Score mínimo para considerar el activo
    
    Returns:
        Score total (0-100)
    """
    pesos = PesosScoring()
    
    # Normalizar momentum_pct (esperado: -5% a +5%)
    momentum_norm = normalizar_valor(
        indicadores.momentum_pct,
        Decimal("-5.00"),
        Decimal("5.00"),
    )
    
    # Normalizar ROC (esperado: -0.1 a +0.1)
    roc_norm = normalizar_valor(
        indicadores.rate_of_change,
        Decimal("-0.1"),
        Decimal("0.1"),
    )
    
    # Normalizar volatilidad (esperado: 0 a 2.0)
    vol_norm = normalizar_valor(
        indicadores.volatilidad,
        Decimal("0.00"),
        Decimal("2.0"),
    )
    
    # Normalizar tendencia EMA (diferencia porcentual con precio actual)
    if indicadores.precio_actual > 0:
        diferencia_pct = (
            abs(indicadores.tendencia_ema - indicadores.precio_actual)
            / indicadores.precio_actual
            * Decimal("100")
        )
        tendencia_norm = normalizar_valor(diferencia_pct, Decimal("0.00"), Decimal("2.0"))
    else:
        tendencia_norm = Decimal("0.00")
    
    # Consistencia ya está en porcentaje (0-100)
    consistencia_norm = indicadores.consistencia
    
    # Winrate histórico (ya está en porcentaje 0-100)
    if rendimiento:
        historial_norm = rendimiento.winrate_dinamico
    else:
        historial_norm = Decimal("50.00")  # Valor neutro si no hay historial
    
    # Calcular score ponderado
    score = (
        pesos.MOMENTUM * momentum_norm
        + pesos.ROC * roc_norm
        + pesos.VOLATILIDAD * vol_norm
        + pesos.TENDENCIA_EMA * tendencia_norm
        + pesos.CONSISTENCIA * consistencia_norm
        + pesos.HISTORIAL * historial_norm
    )
    
    score = score.quantize(Decimal("0.01"))
    
    # Aplicar umbral mínimo
    if score < umbral_minimo:
        return Decimal("0.00")
    
    return min(score, Decimal("100.00"))


def determinar_direccion(
    indicadores: IndicadoresActivo,
) -> str:
    """
    Determina la dirección sugerida (CALL/PUT) basada en múltiples factores.
    
    Args:
        indicadores: Indicadores técnicos del activo
    
    Returns:
        "CALL", "PUT" o "NONE"
    """
    factores_call = 0
    factores_put = 0
    
    # Factor 1: Momentum
    if indicadores.momentum_pct > 0:
        factores_call += 1
    elif indicadores.momentum_pct < 0:
        factores_put += 1
    
    # Factor 2: EMA vs Precio actual
    if indicadores.tendencia_ema > indicadores.precio_actual:
        factores_call += 1
    elif indicadores.tendencia_ema < indicadores.precio_actual:
        factores_put += 1
    
    # Factor 3: Rate of Change
    if indicadores.rate_of_change > 0:
        factores_call += 1
    elif indicadores.rate_of_change < 0:
        factores_put += 1
    
    # Decisión
    if factores_call > factores_put:
        return "CALL"
    elif factores_put > factores_call:
        return "PUT"
    else:
        return "NONE"

