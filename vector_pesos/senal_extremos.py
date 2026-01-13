from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.conf import settings


@dataclass(frozen=True)
class ResultadoSenalExtremos:
    """
    RESULTADO DE LA EVALUACIÓN DE SEÑAL BASADA EN EXTREMOS.
    """

    decision: str  # "COMPRA" | "VENTA" | "NO_OPERAR"
    razon: str  # Razón de la decisión (para debugging)
    precio_entrada_sugerido: Optional[float] = None


def evaluar_senal_extremos(
    vector_extremos: dict[str, float],
    estado_actual: str,
    tick_actual: int,
    tick_entrada: Optional[int] = None,
    ref_extremo_tick: Optional[int] = None,
    ref_extremo_precio: Optional[float] = None,
    umbral_rango_minimo: float = 0.5,
    permitir_put: bool = True,
    permitir_call: bool = True,
) -> ResultadoSenalExtremos:
    """
    EVALÚA SEÑAL BASADA EN EXTREMOS LOCALES.
    
    Lógica:
    1. Detecta si estamos en un máximo o mínimo de los últimos 50 ticks
    2. Espera confirmación (siguiente tick en dirección opuesta)
    3. Entra solo tras confirmación
    
    Args:
        vector_extremos: Diccionario con precios, max_50, min_50, etc.
        estado_actual: Estado de la máquina de estados
        tick_actual: Número de tick actual
        tick_entrada: Tick donde se abrió la operación (si hay)
        umbral_rango_minimo: Rango mínimo para considerar mercado activo
    
    Returns:
        ResultadoSenalExtremos con decisión y razón
    """
    precio_actual = vector_extremos.get("precio_actual", 0.0)
    precio_anterior = vector_extremos.get("precio_anterior", precio_actual)
    max_50 = vector_extremos.get("max_50", precio_actual)
    min_50 = vector_extremos.get("min_50", precio_actual)
    rango_50 = vector_extremos.get("rango_50", 0.0)
    idx_max = vector_extremos.get("idx_max", 0)
    idx_min = vector_extremos.get("idx_min", 0)
    precios = vector_extremos.get("precios", [])
    eps = 0.0001

    # ===== FILTRO DE MERCADO (OBLIGATORIO) =====
    if rango_50 < umbral_rango_minimo:
        return ResultadoSenalExtremos(
            decision="NO_OPERAR",
            razon=f"Rango insuficiente: {rango_50:.4f} < {umbral_rango_minimo}",
        )

    # ===== GESTIÓN DE OPERACIÓN ABIERTA =====
    # En modo real, el contrato de Deriv ya cierra automáticamente por duración (DERIV_DURACION_TICKS).
    # Aquí solo reportamos estado; el cooldown se activa al recibir el cierre del contrato.
    if estado_actual == "EN_OPERACION":
        if tick_entrada is None:
            return ResultadoSenalExtremos(decision="NO_OPERAR", razon="EN_OPERACION sin tick_entrada")
        ticks_desde_entrada = tick_actual - tick_entrada
        dur = int(getattr(settings, "DERIV_DURACION_TICKS", 5) or 5)
        return ResultadoSenalExtremos(decision="NO_OPERAR", razon=f"Operación activa: {ticks_desde_entrada}/{dur} ticks")

    # ===== COOLDOWN =====
    if estado_actual == "COOLDOWN":
        return ResultadoSenalExtremos(
            decision="NO_OPERAR",
            razon="En cooldown",
        )

    # Si por alguna razón quedamos en estados antiguos de espera, reseteamos a IDLE
    # (la estrategia ahora entra directo en la reversión del tick siguiente).
    if estado_actual in {"ESPERANDO_CONFIRMACION_VENTA", "ESPERANDO_CONFIRMACION_COMPRA"}:
        return ResultadoSenalExtremos(decision="IDLE", razon="Reset espera (entrada directa por reversión)")

    # ===== DETECCIÓN DE EXTREMOS =====
    
    # Calcular posición relativa (0=antiguo, 49=actual)
    # Si tenemos menos de 50 ticks, ajustar
    if len(precios) < 50:
        pos_max = idx_max
        pos_min = idx_min
        umbral_frescura = len(precios) - 5  # Últimos 5 ticks disponibles
    else:
        pos_max = idx_max
        pos_min = idx_min
        umbral_frescura = 45  # Últimos 5 ticks de 50

    # Verificar si el extremo es "fresco" (últimos 5 ticks)
    max_fresco = pos_max >= umbral_frescura
    min_fresco = pos_min >= umbral_frescura

    # Contar repeticiones recientes (evitar consolidación)
    if len(precios) >= 10:
        ultimos_10 = precios[-10:]
        conteo_maximos = sum(1 for p in ultimos_10 if p == max_50)
        conteo_minimos = sum(1 for p in ultimos_10 if p == min_50)
    else:
        conteo_maximos = sum(1 for p in precios if p == max_50)
        conteo_minimos = sum(1 for p in precios if p == min_50)

    # ===== REGLA (TU PEDIDO): REVERSIÓN INMEDIATA =====
    # "Se llegó al máximo" en el tick anterior y el tick actual es menor => VENTA.
    # "Se llegó al mínimo" en el tick anterior y el tick actual es mayor => COMPRA.
    if estado_actual == "IDLE":
        n = len(precios)
        # Venta: el tick anterior fue el máximo MÁS RECIENTE del buffer, y el tick actual está por debajo.
        # Usamos idx_max para evitar problemas de precisión float.
        max_en_tick_anterior = (n >= 2) and (int(idx_max) == (n - 2))
        if permitir_put and max_fresco and (conteo_maximos <= 2) and max_en_tick_anterior and (float(precio_actual) < float(max_50)):
            return ResultadoSenalExtremos(
                decision="VENTA",
                razon=f"Reversión desde MAX: idx_max={idx_max} prev={precio_anterior:.3f} max={max_50:.3f} ahora={precio_actual:.3f}",
                precio_entrada_sugerido=float(precio_actual),
            )

        # Compra: el tick anterior fue el mínimo MÁS RECIENTE del buffer, y el tick actual está por encima.
        min_en_tick_anterior = (n >= 2) and (int(idx_min) == (n - 2))
        if permitir_call and min_fresco and (conteo_minimos <= 2) and min_en_tick_anterior and (float(precio_actual) > float(min_50)):
            return ResultadoSenalExtremos(
                decision="COMPRA",
                razon=f"Reversión desde MIN: idx_min={idx_min} prev={precio_anterior:.3f} min={min_50:.3f} ahora={precio_actual:.3f}",
                precio_entrada_sugerido=float(precio_actual),
            )

    # ===== NO HAY SEÑAL =====
    return ResultadoSenalExtremos(
        decision="NO_OPERAR",
        razon="No se cumplen condiciones para operar",
    )
