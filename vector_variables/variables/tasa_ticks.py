from __future__ import annotations


def tasa_ticks(epoch_actual: int, epochs_en_ventana: list[int], ventana_segundos: int) -> float:
    """
    CALCULA LA TASA DE LLEGADA DE TICKS (TICKS POR SEGUNDO) EN UNA VENTANA.

    QUÉ HACE:
    - DADO UN LISTADO DE EPOCHS (SEGUNDOS) RECIENTES, CALCULA:
      ticks_por_segundo = N / ventana_segundos
    - SI ventana_segundos <= 0, DEVUELVE 0.

    POR QUÉ:
    - EL "TICK RATE" REFLEJA LIQUIDEZ / ACTIVIDAD / REGÍMENES.
    - CAMBIOS EN LA INTENSIDAD DE LLEGADA PUEDEN PRECEDER CAMBIOS DE VOLATILIDAD.
    """
    if ventana_segundos <= 0:
        return 0.0
    # epoch_actual SE MANTIENE COMO CONTEXTO PARA FUTURAS EXTENSIONES (p. ej. NORMALIZACIÓN).
    _ = epoch_actual
    return float(len(epochs_en_ventana)) / float(ventana_segundos)


