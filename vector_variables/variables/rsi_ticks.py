from __future__ import annotations


def rsi_ticks(
    retorno_actual: float,
    promedio_ganancias: float | None,
    promedio_perdidas: float | None,
    periodo: int,
) -> tuple[float, float, float]:
    """
    ACTUALIZA RSI BASADO EN TICKS (WILDER) DE FORMA INCREMENTAL.

    QUÉ HACE:
    - MANTIENE PROMEDIOS SUAVIZADOS DE GANANCIAS Y PÉRDIDAS:
      avg_gain_t = (avg_gain_{t-1} * (periodo-1) + gain_t) / periodo
      avg_loss_t = (avg_loss_{t-1} * (periodo-1) + loss_t) / periodo
    - RS = avg_gain / avg_loss
    - RSI = 100 - (100 / (1 + RS))

    POR QUÉ:
    - RSI ES UNA MEDIDA DE MOMENTUM/EXTENSIÓN EN ESCALA CORTA.
    - LA VERSIÓN INCREMENTAL PERMITE OPERAR EN TIEMPO REAL SIN SERIES GRANDES.
    """
    if periodo <= 1:
        return 50.0, 0.0, 0.0

    ganancia = max(retorno_actual, 0.0)
    perdida = max(-retorno_actual, 0.0)

    if promedio_ganancias is None or promedio_perdidas is None:
        avg_gain = ganancia
        avg_loss = perdida
    else:
        avg_gain = ((promedio_ganancias * (periodo - 1)) + ganancia) / float(periodo)
        avg_loss = ((promedio_perdidas * (periodo - 1)) + perdida) / float(periodo)

    if avg_loss == 0.0 and avg_gain == 0.0:
        rsi = 50.0
    elif avg_loss == 0.0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    return float(rsi), float(avg_gain), float(avg_loss)


