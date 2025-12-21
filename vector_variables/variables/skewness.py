from __future__ import annotations

import numpy as np


def skewness(retornos: list[float]) -> float:
    """
    CALCULA LA ASIMETRÍA (SKEWNESS) DE LOS RETORNOS EN UNA VENTANA.

    QUÉ HACE:
    - SKEWNESS = E[((r - mu)/sigma)^3]
    - SI sigma == 0 O NO HAY DATOS, DEVUELVE 0.

    POR QUÉ:
    - CAPTURA SESGOS DIRECCIONALES: COLAS MÁS PESADAS HACIA ARRIBA O HACIA ABAJO.
    - EN MERCADOS CON ESTRUCTURA, LA ASIMETRÍA APORTA INFORMACIÓN MÁS ALLÁ DE LA VARIANZA.
    """
    if len(retornos) < 3:
        return 0.0
    arr = np.asarray(retornos, dtype=float)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=0))
    if sigma == 0.0:
        return 0.0
    z = (arr - mu) / sigma
    return float(np.mean(z**3))


