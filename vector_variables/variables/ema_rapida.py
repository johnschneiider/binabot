from __future__ import annotations


def ema_rapida(precio_actual: float, ema_previa: float | None, periodo: int) -> float:
    """
    ACTUALIZA EMA RÁPIDA (EXPONENTIAL MOVING AVERAGE) EN TIEMPO REAL.

    QUÉ HACE:
    - EMA_t = alpha * precio_t + (1 - alpha) * EMA_{t-1}
    - alpha = 2 / (periodo + 1)
    - SI NO HAY EMA PREVIA, INICIALIZA EN EL PRECIO ACTUAL.

    POR QUÉ:
    - CAPTURA TENDENCIA DE CORTO PLAZO EN TICKS SIN NECESIDAD DE ALMACENAR TODA LA SERIE.
    """
    if periodo <= 1:
        return float(precio_actual)
    alpha = 2.0 / (float(periodo) + 1.0)
    if ema_previa is None:
        return float(precio_actual)
    return (alpha * float(precio_actual)) + ((1.0 - alpha) * float(ema_previa))


