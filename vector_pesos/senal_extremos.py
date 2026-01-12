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
    if estado_actual == "EN_OPERACION":
        if tick_entrada is None:
            return ResultadoSenalExtremos(
                decision="NO_OPERAR",
                razon="En operación pero sin tick_entrada",
            )
        
        ticks_desde_entrada = tick_actual - tick_entrada
        
        # Cierre por tiempo (5 ticks)
        if ticks_desde_entrada >= 5:
            return ResultadoSenalExtremos(
                decision="CERRAR",
                razon=f"Cierre por tiempo: {ticks_desde_entrada} ticks",
            )
        
        return ResultadoSenalExtremos(
            decision="NO_OPERAR",
            razon=f"Operación activa: {ticks_desde_entrada} ticks desde entrada",
        )

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

    # ===== DETECCIÓN DE MÁXIMO OPERATIVO (PARA VENTA) =====
    if estado_actual == "IDLE" or estado_actual == "ESPERANDO_CONFIRMACION_VENTA":
        # Condiciones para máximo válido
        en_maximo = abs(precio_actual - max_50) < 0.0001  # Tolerancia por precisión float
        maximo_fresco = max_fresco
        no_consolidado = conteo_maximos <= 2
        precio_subio = precio_actual > precio_anterior

        if en_maximo and maximo_fresco and no_consolidado and precio_subio:
            # Máximo válido detectado
            if estado_actual == "IDLE":
                # Cambiar a esperando confirmación
                return ResultadoSenalExtremos(
                    decision="ESPERANDO_VENTA",
                    razon=f"Máximo detectado: {max_50:.5f} (posición {pos_max})",
                )
            elif estado_actual == "ESPERANDO_CONFIRMACION_VENTA":
                # Verificar confirmación: precio debe bajar
                if precio_actual < precio_anterior:
                    return ResultadoSenalExtremos(
                        decision="VENTA",
                        razon=f"Confirmación venta: precio bajó de {precio_anterior:.5f} a {precio_actual:.5f}",
                        precio_entrada_sugerido=precio_anterior,
                    )
                else:
                    # No se confirmó, volver a IDLE
                    return ResultadoSenalExtremos(
                        decision="IDLE",
                        razon="Confirmación venta fallida: precio no bajó",
                    )

    # ===== DETECCIÓN DE MÍNIMO OPERATIVO (PARA COMPRA) =====
    if estado_actual == "IDLE" or estado_actual == "ESPERANDO_CONFIRMACION_COMPRA":
        # Condiciones para mínimo válido
        en_minimo = abs(precio_actual - min_50) < 0.0001
        minimo_fresco = min_fresco
        no_consolidado = conteo_minimos <= 2
        precio_bajo = precio_actual < precio_anterior

        if en_minimo and minimo_fresco and no_consolidado and precio_bajo:
            # Mínimo válido detectado
            if estado_actual == "IDLE":
                # Cambiar a esperando confirmación
                return ResultadoSenalExtremos(
                    decision="ESPERANDO_COMPRA",
                    razon=f"Mínimo detectado: {min_50:.5f} (posición {pos_min})",
                )
            elif estado_actual == "ESPERANDO_CONFIRMACION_COMPRA":
                # Verificar confirmación: precio debe subir
                if precio_actual > precio_anterior:
                    return ResultadoSenalExtremos(
                        decision="COMPRA",
                        razon=f"Confirmación compra: precio subió de {precio_anterior:.5f} a {precio_actual:.5f}",
                        precio_entrada_sugerido=precio_anterior,
                    )
                else:
                    # No se confirmó, volver a IDLE
                    return ResultadoSenalExtremos(
                        decision="IDLE",
                        razon="Confirmación compra fallida: precio no subió",
                    )

    # ===== RESET DE ESTADOS DE ESPERA SI NO SE CUMPLEN CONDICIONES =====
    if estado_actual == "ESPERANDO_CONFIRMACION_VENTA":
        # Si ya no estamos en el máximo, resetear
        if not (abs(precio_actual - max_50) < 0.0001):
            return ResultadoSenalExtremos(
                decision="IDLE",
                razon="Ya no estamos en máximo, resetear espera",
            )

    if estado_actual == "ESPERANDO_CONFIRMACION_COMPRA":
        # Si ya no estamos en el mínimo, resetear
        if not (abs(precio_actual - min_50) < 0.0001):
            return ResultadoSenalExtremos(
                decision="IDLE",
                razon="Ya no estamos en mínimo, resetear espera",
            )

    # ===== NO HAY SEÑAL =====
    return ResultadoSenalExtremos(
        decision="NO_OPERAR",
        razon="No se cumplen condiciones para operar",
    )
