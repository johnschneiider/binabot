from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionRiesgo:
    """
    RESULTADO DE LA CAPA DE RIESGO.
    """

    permitido: bool
    motivo: str
    tamanio_posicion: float


class GestorRiesgo:
    """
    GESTIÓN DE RIESGO ESTRICTA (INNEGOCIABLE).

    REGLAS:
    - RIESGO MÁXIMO POR OPERACIÓN: 1% (CONFIGURABLE).
    - BLOQUEO SI SE SUPERA DRAWDOWN (CONFIGURABLE).

    NOTA:
    - ESTE MÓDULO NO DECIDE COMPRA/VENTA. SOLO PERMITE O BLOQUEA Y CALCULA TAMAÑOS.
    """

    def __init__(
        self,
        capital_inicial: float,
        max_riesgo_por_operacion: float,
        max_drawdown: float,
    ) -> None:
        self.capital_inicial = float(capital_inicial)
        self.max_riesgo_por_operacion = float(max_riesgo_por_operacion)
        self.max_drawdown = float(max_drawdown)

        self.capital_actual = float(capital_inicial)
        self.max_capital_historico = float(capital_inicial)
        self.bloqueado = False

    def registrar_equity(self, capital_actual: float) -> None:
        """
        ACTUALIZA CAPITAL Y EVALÚA DRAWDOWN PARA BLOQUEO.
        """
        self.capital_actual = float(capital_actual)
        self.max_capital_historico = max(self.max_capital_historico, self.capital_actual)

        if self.max_capital_historico <= 0.0:
            self.bloqueado = True
            return

        drawdown = 1.0 - (self.capital_actual / self.max_capital_historico)
        if drawdown >= self.max_drawdown:
            self.bloqueado = True

    def riesgo_disponible(self) -> float:
        """
        CAPITAL ARRIESGABLE POR OPERACIÓN.
        """
        return max(0.0, self.capital_actual * self.max_riesgo_por_operacion)

    def calcular_tamanio_posicion(self, distancia_stop: float) -> float:
        """
        CALCULA TAMAÑO DE POSICIÓN DADO UN STOP EN UNIDADES DE PRECIO.

        QUÉ HACE:
        - size = riesgo_monetario / distancia_stop

        POR QUÉ:
        - IMPONE QUE LA PÉRDIDA MÁXIMA ESPERADA POR STOP SEA <= 1% DEL CAPITAL.
        """
        if distancia_stop <= 0.0:
            return 0.0
        return self.riesgo_disponible() / float(distancia_stop)

    def autorizar_operacion(self, distancia_stop: float) -> DecisionRiesgo:
        """
        DECIDE SI SE PUEDE OPERAR Y DEVUELVE TAMAÑO DE POSICIÓN.
        """
        if self.bloqueado:
            return DecisionRiesgo(False, "BLOQUEADO_POR_DRAWDOWN", 0.0)

        if self.capital_actual <= 0.0:
            return DecisionRiesgo(False, "CAPITAL_NO_POSITIVO", 0.0)

        tamanio = self.calcular_tamanio_posicion(distancia_stop)
        if tamanio <= 0.0:
            return DecisionRiesgo(False, "STOP_INVALIDO_O_RIESGO_CERO", 0.0)

        return DecisionRiesgo(True, "OK", float(tamanio))


