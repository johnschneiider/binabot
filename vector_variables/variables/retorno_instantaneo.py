from __future__ import annotations


def retorno_instantaneo(precio_actual: float, precio_anterior: float | None) -> float:
    """
    CALCULA EL RETORNO INSTANTÁNEO ENTRE DOS TICKS.

    QUÉ HACE:
    - DEVUELVE (p_t / p_{t-1} - 1). SI NO HAY PRECIO ANTERIOR, DEVUELVE 0.

    POR QUÉ:
    - EL RETORNO ES LA UNIDAD BÁSICA DE INFORMACIÓN PARA MODELAR DINÁMICA DE MERCADO
      Y ES LA BASE PARA VOLATILIDAD, ASIMETRÍA (SKEWNESS) Y COLAS (KURTOSIS).
    """
    if precio_anterior is None or precio_anterior == 0:
        return 0.0
    return (precio_actual / precio_anterior) - 1.0


