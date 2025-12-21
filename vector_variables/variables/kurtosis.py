from __future__ import annotations

import numpy as np


def kurtosis(retornos: list[float]) -> float:
    """
    CALCULA LA KURTOSIS (EXCESO DE COLA) DE LOS RETORNOS EN UNA VENTANA.

    QUÉ HACE:
    - KURTOSIS = E[((r - mu)/sigma)^4] - 3
      (EXCESO DE KURTOSIS PARA QUE NORMAL -> 0)
    - SI sigma == 0 O NO HAY DATOS, DEVUELVE 0.

    POR QUÉ:
    - MIDE COLAS PESADAS: EVENTOS EXTREMOS RELATIVOS A UNA DISTRIBUCIÓN NORMAL.
    - ES CRÍTICO PARA SISTEMAS INSTITUCIONALES DONDE EL RIESGO DE COLA DOMINA.
    """
    if len(retornos) < 4:
        return 0.0
    arr = np.asarray(retornos, dtype=float)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=0))
    if sigma == 0.0:
        return 0.0
    z = (arr - mu) / sigma
    return float(np.mean(z**4) - 3.0)


