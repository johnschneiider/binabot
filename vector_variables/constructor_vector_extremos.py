from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from django.conf import settings


@dataclass(frozen=True)
class Tick:
    """
    REPRESENTA UN TICK NORMALIZADO PARA EL MOTOR CUANTITATIVO.
    """

    precio: float
    epoch: int


@dataclass
class EstadoExtremos:
    """
    ESTADO DE LA MÁQUINA DE ESTADOS PARA OPERAR EN EXTREMOS.
    """

    estado: str  # IDLE, ESPERANDO_CONFIRMACION_VENTA, ESPERANDO_CONFIRMACION_COMPRA, EN_OPERACION, COOLDOWN
    ultimo_extremo_operado: Optional[str]  # None, "MAX", "MIN"
    ticks_cooldown_restantes: int
    precio_entrada: Optional[float]
    tick_entrada: Optional[int]
    tipo_operacion: Optional[str]  # None, "VENTA", "COMPRA"
    # Referencia del extremo detectado para confirmación en el tick siguiente.
    ref_extremo_tipo: Optional[str]  # None, "MAX", "MIN"
    ref_extremo_precio: Optional[float]
    ref_extremo_tick: Optional[int]


class ConstructorVectorExtremos:
    """
    CONSTRUCTOR SIMPLIFICADO PARA ESTRATEGIA DE EXTREMOS.
    
    MANTIENE ÚNICAMENTE LOS ÚLTIMOS N TICKS (configurable) Y CALCULA EXTREMOS.
    """

    def __init__(self, ventana_ticks: int | None = None) -> None:
        self.ventana_ticks = int(ventana_ticks or getattr(settings, "EXTREMOS_VENTANA_TICKS", 100) or 100)
        self._precios: deque[float] = deque(maxlen=self.ventana_ticks)
        self._ticks_procesados: int = 0
        self._estado: EstadoExtremos = EstadoExtremos(
            estado="IDLE",
            ultimo_extremo_operado=None,
            ticks_cooldown_restantes=0,
            precio_entrada=None,
            tick_entrada=None,
            tipo_operacion=None,
            ref_extremo_tipo=None,
            ref_extremo_precio=None,
            ref_extremo_tick=None,
        )

    def ticks_procesados(self) -> int:
        """Devuelve cuántos ticks han entrado."""
        return int(self._ticks_procesados)

    def listo_para_operar(self, min_ticks: int | None = None) -> bool:
        """Indica si hay suficientes ticks para operar."""
        objetivo = int(min_ticks or self.ventana_ticks)
        return self._ticks_procesados >= objetivo

    def actualizar_con_tick(self, tick: Tick) -> dict[str, float]:
        """
        ACTUALIZA EL VECTOR CON UN NUEVO TICK Y CALCULA VARIABLES DE EXTREMOS.
        
        Retorna un diccionario con:
        - precios: lista de últimos N precios
        - max_50: máximo de los últimos N ticks (nombre histórico por compatibilidad)
        - min_50: mínimo de los últimos N ticks (nombre histórico por compatibilidad)
        - rango_50: diferencia entre max y min (nombre histórico por compatibilidad)
        - precio_actual: último precio
        - precio_anterior: penúltimo precio
        - idx_max: índice del máximo más reciente (0=antiguo, N-1=actual)
        - idx_min: índice del mínimo más reciente
        """
        self._ticks_procesados += 1
        self._precios.append(float(tick.precio))

        # Si aún no tenemos suficientes ticks, retornar valores por defecto
        if len(self._precios) < 2:
            return {
                "precio_actual": float(tick.precio),
                "precio_anterior": float(tick.precio),
                "max_50": float(tick.precio),
                "min_50": float(tick.precio),
                "rango_50": 0.0,
                "idx_max": 0,
                "idx_min": 0,
                "precios": list(self._precios),
            }

        precios_lista = list(self._precios)
        precio_actual = precios_lista[-1]
        precio_anterior = precios_lista[-2] if len(precios_lista) >= 2 else precio_actual

        # Calcular máximo y mínimo
        max_50 = max(precios_lista)
        min_50 = min(precios_lista)
        rango_50 = max_50 - min_50

        # Encontrar el índice del máximo más reciente (último donde ocurrió)
        idx_max = len(precios_lista) - 1
        for i in range(len(precios_lista) - 1, -1, -1):
            if precios_lista[i] == max_50:
                idx_max = i
                break

        # Encontrar el índice del mínimo más reciente
        idx_min = len(precios_lista) - 1
        for i in range(len(precios_lista) - 1, -1, -1):
            if precios_lista[i] == min_50:
                idx_min = i
                break

        # Convertir índices a posición relativa (0=antiguo, 49=actual)
        # Si el vector tiene menos de 50 elementos, ajustar
        if len(precios_lista) < self.ventana_ticks:
            idx_max_relativo = idx_max
            idx_min_relativo = idx_min
        else:
            idx_max_relativo = idx_max
            idx_min_relativo = idx_min

        return {
            "precio_actual": precio_actual,
            "precio_anterior": precio_anterior,
            "max_50": max_50,
            "min_50": min_50,
            "rango_50": rango_50,
            "idx_max": idx_max_relativo,
            "idx_min": idx_min_relativo,
            "precios": precios_lista,
        }

    def obtener_estado(self) -> EstadoExtremos:
        """Retorna el estado actual de la máquina de estados."""
        return self._estado

    def actualizar_estado(self, nuevo_estado: str, **kwargs) -> None:
        """Actualiza el estado de la máquina de estados."""
        if nuevo_estado == "IDLE":
            self._estado = EstadoExtremos(
                estado="IDLE",
                ultimo_extremo_operado=self._estado.ultimo_extremo_operado,
                ticks_cooldown_restantes=0,
                precio_entrada=None,
                tick_entrada=None,
                tipo_operacion=None,
                ref_extremo_tipo=None,
                ref_extremo_precio=None,
                ref_extremo_tick=None,
            )
        elif nuevo_estado == "ESPERANDO_CONFIRMACION_VENTA":
            self._estado = EstadoExtremos(
                estado="ESPERANDO_CONFIRMACION_VENTA",
                ultimo_extremo_operado=self._estado.ultimo_extremo_operado,
                ticks_cooldown_restantes=0,
                precio_entrada=None,
                tick_entrada=None,
                tipo_operacion=None,
                ref_extremo_tipo="MAX",
                ref_extremo_precio=kwargs.get("ref_extremo_precio"),
                ref_extremo_tick=kwargs.get("ref_extremo_tick"),
            )
        elif nuevo_estado == "ESPERANDO_CONFIRMACION_COMPRA":
            self._estado = EstadoExtremos(
                estado="ESPERANDO_CONFIRMACION_COMPRA",
                ultimo_extremo_operado=self._estado.ultimo_extremo_operado,
                ticks_cooldown_restantes=0,
                precio_entrada=None,
                tick_entrada=None,
                tipo_operacion=None,
                ref_extremo_tipo="MIN",
                ref_extremo_precio=kwargs.get("ref_extremo_precio"),
                ref_extremo_tick=kwargs.get("ref_extremo_tick"),
            )
        elif nuevo_estado == "EN_OPERACION":
            self._estado = EstadoExtremos(
                estado="EN_OPERACION",
                ultimo_extremo_operado=kwargs.get("ultimo_extremo_operado", self._estado.ultimo_extremo_operado),
                ticks_cooldown_restantes=0,
                precio_entrada=kwargs.get("precio_entrada"),
                tick_entrada=kwargs.get("tick_entrada"),
                tipo_operacion=kwargs.get("tipo_operacion"),
                ref_extremo_tipo=None,
                ref_extremo_precio=None,
                ref_extremo_tick=None,
            )
        elif nuevo_estado == "COOLDOWN":
            self._estado = EstadoExtremos(
                estado="COOLDOWN",
                ultimo_extremo_operado=self._estado.ultimo_extremo_operado,
                ticks_cooldown_restantes=kwargs.get("ticks_cooldown_restantes", 25),
                precio_entrada=None,
                tick_entrada=None,
                tipo_operacion=None,
                ref_extremo_tipo=None,
                ref_extremo_precio=None,
                ref_extremo_tick=None,
            )

    def decrementar_cooldown(self) -> None:
        """Decrementa el contador de cooldown."""
        if self._estado.estado == "COOLDOWN" and self._estado.ticks_cooldown_restantes > 0:
            self._estado.ticks_cooldown_restantes -= 1
            if self._estado.ticks_cooldown_restantes == 0:
                self.actualizar_estado("IDLE")
