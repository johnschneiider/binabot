from __future__ import annotations

from datetime import time
from typing import Iterable, List

from django.utils import timezone

from core.models import ActivoPermitido


def _minutos_entre(hora1: time, hora2: time) -> int:
    """Devuelve la distancia mínima en minutos entre dos horas (círculo de 24h)."""
    minutos1 = hora1.hour * 60 + hora1.minute
    minutos2 = hora2.hour * 60 + hora2.minute
    diff = abs(minutos1 - minutos2)
    return min(diff, 1440 - diff)


def priorizar_activos_por_horario(
    activos: Iterable[ActivoPermitido],
    ventana_minutos: int = 60,
) -> List[ActivoPermitido]:
    """
    Ordena los activos dando prioridad a los pares forex cuya hora óptima
    esté cercana al horario actual. El resto mantiene el orden basado en winrate.
    """

    ahora = timezone.localtime().time()

    def sort_key(activo: ActivoPermitido) -> tuple:
        es_forex = activo.nombre.startswith("frx")
        hora_optima = activo.hora_mejor_simulacion
        proximidad = (
            _minutos_entre(ahora, hora_optima)
            if hora_optima is not None
            else 1440
        )
        en_ventana = es_forex and hora_optima and proximidad <= ventana_minutos
        prioridad_general = 0 if en_ventana else (1 if es_forex else 2)
        # Convertir Decimal a float para evitar problemas al ordenar
        winrate = float(activo.winrate_simulacion or 0)
        return (
            prioridad_general,
            proximidad if es_forex else 1440,
            -winrate,
            activo.nombre,
        )

    return sorted(activos, key=sort_key)

