from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from django.conf import settings

from .variables.ema_lenta import ema_lenta
from .variables.ema_rapida import ema_rapida
from .variables.kurtosis import kurtosis
from .variables.retorno_instantaneo import retorno_instantaneo
from .variables.rsi_ticks import rsi_ticks
from .variables.skewness import skewness
from .variables.tasa_ticks import tasa_ticks
from .variables.volatilidad_local import volatilidad_local


@dataclass(frozen=True)
class Tick:
    """
    REPRESENTA UN TICK NORMALIZADO PARA EL MOTOR CUANTITATIVO.

    NOTA:
    - SE MANTIENE MINIMALISTA: precio + epoch (segundos).
    """

    precio: float
    epoch: int


class ConstructorVectorMercado:
    """
    CONSTRUYE Y MANTIENE EL VECTOR DE ESTADO DEL MERCADO (x) EN TIEMPO REAL.

    PRINCIPIO INSTITUCIONAL:
    - ESTE MÓDULO SOLO HABLA DE "MERCADO": MEDICIONES, ESTADÍSTICAS, REGÍMENES.
    - NO TOMA DECISIONES DE COMPRA/VENTA. ESO VIVE EN ESTRATEGIA (PESOS) + FUNCIÓN CENTRAL.
    """

    def __init__(
        self,
        ventana_retornos: int | None = None,
        ventana_ticks_rate_segundos: int | None = None,
        periodo_ema_rapida: int = 10,
        periodo_ema_lenta: int = 50,
        periodo_rsi: int = 14,
    ) -> None:
        self.ventana_retornos = int(ventana_retornos or settings.VENTANA_RETORNOS)
        self.ventana_ticks_rate_segundos = int(
            ventana_ticks_rate_segundos or settings.VENTANA_TICKS_RATE
        )
        self.periodo_ema_rapida = int(periodo_ema_rapida)
        self.periodo_ema_lenta = int(periodo_ema_lenta)
        self.periodo_rsi = int(periodo_rsi)

        # ESTADO INCREMENTAL
        self._precio_anterior: float | None = None
        self._ema_rapida: float | None = None
        self._ema_lenta: float | None = None
        self._rsi_avg_gain: float | None = None
        self._rsi_avg_loss: float | None = None
        self._ticks_procesados: int = 0

        self._retornos: deque[float] = deque(maxlen=self.ventana_retornos)
        self._epochs_ticks: deque[int] = deque(maxlen=self.ventana_ticks_rate_segundos * 10)

    def ticks_procesados(self) -> int:
        """
        DEVUELVE CUÁNTOS TICKS HAN ENTRADO AL CONSTRUCTOR (PARA CALENTAMIENTO/WARM-UP).
        """
        return int(self._ticks_procesados)

    def listo_para_operar(self, min_ticks: int | None = None) -> bool:
        """
        INDICA SI HAY SUFICIENTE HISTORIA PARA OPERAR SIN INESTABILIDAD ESTADÍSTICA.

        POR QUÉ:
        - AL INICIO, VOLATILIDAD/RSI/MOMENTOS SON INESTABLES Y PUEDEN GENERAR TAMAÑOS DE POSICIÓN
          ABSURDOS SI SE USAN PARA STOP/RIESGO.
        """
        objetivo = int(min_ticks or settings.MIN_TICKS_CALENTAMIENTO)
        return self._ticks_procesados >= objetivo

    def actualizar_con_tick(self, tick: Tick) -> dict[str, float]:
        """
        ACTUALIZA ESTADO CON UN TICK Y DEVUELVE EL VECTOR (x) COMO DICCIONARIO.
        """
        self._ticks_procesados += 1
        r_inst = retorno_instantaneo(tick.precio, self._precio_anterior)
        self._precio_anterior = tick.precio

        self._retornos.append(float(r_inst))

        # EMA RÁPIDA / LENTA
        self._ema_rapida = ema_rapida(tick.precio, self._ema_rapida, self.periodo_ema_rapida)
        self._ema_lenta = ema_lenta(tick.precio, self._ema_lenta, self.periodo_ema_lenta)

        # RSI TICKS (WILDER INCREMENTAL)
        rsi, self._rsi_avg_gain, self._rsi_avg_loss = rsi_ticks(
            retorno_actual=float(r_inst),
            promedio_ganancias=self._rsi_avg_gain,
            promedio_perdidas=self._rsi_avg_loss,
            periodo=self.periodo_rsi,
        )

        # TICK RATE: MANTENER SOLO EPOCHS DENTRO DE LA VENTANA (SEGUNDOS)
        self._epochs_ticks.append(int(tick.epoch))
        limite_inferior = int(tick.epoch) - int(self.ventana_ticks_rate_segundos)
        while self._epochs_ticks and self._epochs_ticks[0] < limite_inferior:
            self._epochs_ticks.popleft()

        retornos_lista = list(self._retornos)

        vector: dict[str, float] = {
            # VARIABLES OBLIGATORIAS
            "retorno_instantaneo": float(r_inst),
            "ema_rapida": float(self._ema_rapida or tick.precio),
            "ema_lenta": float(self._ema_lenta or tick.precio),
            "rsi_ticks": float(rsi),
            "volatilidad_local": float(volatilidad_local(retornos_lista)),
            "skewness": float(skewness(retornos_lista)),
            "kurtosis": float(kurtosis(retornos_lista)),
            "tasa_ticks": float(tasa_ticks(tick.epoch, list(self._epochs_ticks), self.ventana_ticks_rate_segundos)),
        }

        return vector


