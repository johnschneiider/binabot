from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class _EstadoNormalizacion:
    """
    ESTADO POR VARIABLE PARA NORMALIZACIÓN ONLINE.

    POR QUÉ:
    - EN TIEMPO REAL NO TENEMOS DATASET COMPLETO PARA STANDARDIZAR.
    - USAMOS ESTADÍSTICAS EWMA (MEDIA/VARIANZA) PARA ADAPTARNOS A CAMBIOS DE RÉGIMEN.
    """

    n: int = 0
    media: float = 0.0
    var: float = 0.0  # VARIANZA EWMA (NO INSISTE EN SER INSesgada; ES OPERATIVA)


class NormalizadorOnlinePorVariable:
    """
    NORMALIZA UN VECTOR DE MERCADO (x) VARIABLE A VARIABLE.

    REGLA:
    - PRODUCE z_i = (x_i - media_i) / std_i

    IMPORTANTE:
    - SIN NORMALIZACIÓN, w^T x QUEDA DOMINADO POR VARIABLES DE MAYOR ESCALA (EJ: EMAs).
    - CON NORMALIZACIÓN, LOS PESOS SE VUELVEN INTERPRETABLES Y ESTABLES.
    """

    def __init__(
        self,
        *,
        alpha: float = 0.01,
        min_std: float = 1e-8,
        clip: float | None = 5.0,
    ) -> None:
        a = float(alpha)
        if not (0.0 < a <= 1.0):
            raise ValueError("alpha debe estar en (0, 1].")
        self._alpha = a
        self._min_std = float(min_std)
        self._clip = float(clip) if clip is not None else None
        self._estado: dict[str, _EstadoNormalizacion] = {}

    def actualizar_y_normalizar(self, vector: dict[str, float]) -> dict[str, float]:
        """
        ACTUALIZA LAS ESTADÍSTICAS Y DEVUELVE EL VECTOR NORMALIZADO.

        NOTA:
        - EN LAS PRIMERAS OBSERVACIONES, DEVUELVE 0.0 PARA EVITAR SEÑALES ESPURIAS.
        """
        salida: dict[str, float] = {}
        for nombre, x in vector.items():
            x_f = float(x)
            if not math.isfinite(x_f):
                salida[nombre] = 0.0
                continue

            st = self._estado.get(nombre)
            if st is None:
                st = _EstadoNormalizacion(n=0, media=0.0, var=0.0)
                self._estado[nombre] = st

            st.n += 1
            if st.n == 1:
                # ARRANQUE: NO HAY DISPERSIÓN AÚN.
                st.media = x_f
                st.var = 0.0
                salida[nombre] = 0.0
                continue

            # EWMA DE MEDIA
            prev_media = float(st.media)
            st.media = (1.0 - self._alpha) * prev_media + self._alpha * x_f

            # EWMA DE VARIANZA (DESVIACIÓN AL CUADRADO RESPECTO A LA MEDIA ACTUALIZADA)
            dev = x_f - float(st.media)
            st.var = (1.0 - self._alpha) * float(st.var) + self._alpha * (dev * dev)

            std = math.sqrt(max(float(st.var), 0.0))
            std = max(std, self._min_std)
            z = (x_f - float(st.media)) / std

            if self._clip is not None:
                c = float(self._clip)
                z = max(-c, min(c, z))
            if not math.isfinite(z):
                z = 0.0
            salida[nombre] = float(z)

        return salida

    def snapshot(self) -> dict[str, dict[str, float]]:
        """
        DEVUELVE UN SNAPSHOT DEL ESTADO (PARA DEBUG/AUDITORÍA).
        """
        return {
            k: {"n": float(v.n), "media": float(v.media), "var": float(v.var)}
            for k, v in self._estado.items()
        }


