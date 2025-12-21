from __future__ import annotations


def ema_lenta(precio_actual: float, ema_previa: float | None, periodo: int) -> float:
    """
    ACTUALIZA EMA LENTA (EXPONENTIAL MOVING AVERAGE) EN TIEMPO REAL.

    QUÉ HACE:
    - MISMA FORMULACIÓN QUE LA EMA RÁPIDA, PERO CON UN PERIODO MAYOR.

    POR QUÉ:
    - REPRESENTA EL "NIVEL" O TENDENCIA DE MAYOR ESCALA.
      COMPARAR EMA RÁPIDA VS EMA LENTA ES UNA FORMA CLÁSICA DE MEDIR MOMENTUM/TENDENCIA.
    """
    if periodo <= 1:
        return float(precio_actual)
    alpha = 2.0 / (float(periodo) + 1.0)
    if ema_previa is None:
        return float(precio_actual)
    return (alpha * float(precio_actual)) + ((1.0 - alpha) * float(ema_previa))


