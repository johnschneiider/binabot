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

    # ===== REGLA NUEVA (PEDIDA): MÁXIMO → (SIGUIENTE TICK < MÁXIMO) ⇒ VENTA =====
    # Paso 1: detectar "tocó máximo" en IDLE y marcar espera.
    if estado_actual == "IDLE":
        en_maximo = abs(precio_actual - max_50) < 0.0001
        if en_maximo and max_fresco and (conteo_maximos <= 2):
            return ResultadoSenalExtremos(
                decision="ESPERANDO_VENTA",
                razon=f"Max tocado: {max_50:.3f} (esperando 1 tick de confirmación)",
            )

    # Paso 2: confirmación en el tick siguiente: precio_actual < ref_extremo_precio
    if estado_actual == "ESPERANDO_CONFIRMACION_VENTA":
        if ref_extremo_tick is None or ref_extremo_precio is None:
            return ResultadoSenalExtremos(decision="IDLE", razon="Falta ref_extremo para confirmar VENTA")
        # Solo vale el tick inmediatamente siguiente.
        if tick_actual != int(ref_extremo_tick) + 1:
            return ResultadoSenalExtremos(decision="IDLE", razon="VENTA: ventana de confirmación vencida")
        if float(precio_actual) < float(ref_extremo_precio):
            return ResultadoSenalExtremos(
                decision="VENTA",
                razon=f"Confirmación VENTA: {precio_actual:.3f} < max_ref {float(ref_extremo_precio):.3f}",
                precio_entrada_sugerido=precio_actual,
            )
        return ResultadoSenalExtremos(decision="IDLE", razon="Confirmación VENTA fallida (no bajó)")

    # ===== REGLA SIMÉTRICA: MÍNIMO → (SIGUIENTE TICK > MÍNIMO) ⇒ COMPRA =====
    if estado_actual == "IDLE":
        en_minimo = abs(precio_actual - min_50) < 0.0001
        if en_minimo and min_fresco and (conteo_minimos <= 2):
            return ResultadoSenalExtremos(
                decision="ESPERANDO_COMPRA",
                razon=f"Min tocado: {min_50:.3f} (esperando 1 tick de confirmación)",
            )

    if estado_actual == "ESPERANDO_CONFIRMACION_COMPRA":
        if ref_extremo_tick is None or ref_extremo_precio is None:
            return ResultadoSenalExtremos(decision="IDLE", razon="Falta ref_extremo para confirmar COMPRA")
        if tick_actual != int(ref_extremo_tick) + 1:
            return ResultadoSenalExtremos(decision="IDLE", razon="COMPRA: ventana de confirmación vencida")
        if float(precio_actual) > float(ref_extremo_precio):
            return ResultadoSenalExtremos(
                decision="COMPRA",
                razon=f"Confirmación COMPRA: {precio_actual:.3f} > min_ref {float(ref_extremo_precio):.3f}",
                precio_entrada_sugerido=precio_actual,
            )
        return ResultadoSenalExtremos(decision="IDLE", razon="Confirmación COMPRA fallida (no subió)")

    # ===== NO HAY SEÑAL =====
    return ResultadoSenalExtremos(
        decision="NO_OPERAR",
        razon="No se cumplen condiciones para operar",
    )
