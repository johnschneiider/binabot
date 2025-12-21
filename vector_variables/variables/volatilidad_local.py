from __future__ import annotations

import numpy as np


def volatilidad_local(retornos: list[float]) -> float:
    """
    CALCULA VOLATILIDAD LOCAL SOBRE UNA VENTANA DE RETORNOS.

    QUÉ HACE:
    - DEVUELVE LA DESVIACIÓN ESTÁNDAR (MUESTRAL) DE LOS RETORNOS EN LA VENTANA.
    - SI NO HAY SUFICIENTES DATOS, DEVUELVE 0.

    POR QUÉ:
    - LA VOLATILIDAD ES UNA MEDIDA CLAVE PARA ESCALAR RIESGO, UMBRALES Y TAMAÑO DE POSICIÓN.
    """
    if len(retornos) < 2:
        return 0.0
    arr = np.asarray(retornos, dtype=float)
    return float(np.std(arr, ddof=1))


