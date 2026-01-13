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
    ventana = int(getattr(settings, "EXTREMOS_VENTANA_TICKS", 100) or 100)
    frescura = int(getattr(settings, "EXTREMOS_FRESCURA_TICKS", 5) or 5)
    ventana_rep = int(getattr(settings, "EXTREMOS_VENTANA_REPETICIONES", 10) or 10)
    max_rep = int(getattr(settings, "EXTREMOS_MAX_REPETICIONES", 2) or 2)
    min_rev_frac = float(getattr(settings, "EXTREMOS_MIN_REVERSION_FRAC", 0.05) or 0.05)
    min_rev_abs = float(getattr(settings, "EXTREMOS_MIN_REVERSION_ABS", 0.0) or 0.0)
    min_rev = max(min_rev_abs, min_rev_frac * float(rango_50 or 0.0))

    # Promedio de movimiento reciente (para exigir retroceso “real” y no ruido).
    # - EXTREMOS_PROMEDIO_DELTA_TICKS: cuántos deltas considerar
    # - EXTREMOS_PROMEDIO_DELTA_FACTOR: multiplicador sobre el promedio
    avg_delta_ticks = int(getattr(settings, "EXTREMOS_PROMEDIO_DELTA_TICKS", 20) or 20)
    avg_delta_factor = float(getattr(settings, "EXTREMOS_PROMEDIO_DELTA_FACTOR", 1.0) or 1.0)
    avg_abs_delta = 0.0
    try:
        n_p = len(precios)
        if n_p >= 3:
            # Usamos los últimos K deltas (|p[i]-p[i-1]|) para capturar el “ruido” típico reciente.
            k = min(max(1, avg_delta_ticks), n_p - 1)  # cantidad de deltas
            start = n_p - k
            deltas = [abs(float(precios[i]) - float(precios[i - 1])) for i in range(start, n_p)]
            avg_abs_delta = (sum(deltas) / float(len(deltas))) if deltas else 0.0
    except Exception:
        avg_abs_delta = 0.0

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
    
    # Calcular posición relativa (0=antiguo, N-1=actual)
    # Si tenemos menos de N ticks, ajustar
    if len(precios) < ventana:
        pos_max = idx_max
        pos_min = idx_min
        umbral_frescura = max(0, len(precios) - frescura)  # Últimos `frescura` ticks disponibles
    else:
        pos_max = idx_max
        pos_min = idx_min
        umbral_frescura = max(0, ventana - frescura)  # Últimos `frescura` ticks de `ventana`

    # Verificar si el extremo es "fresco" (últimos 5 ticks)
    max_fresco = pos_max >= umbral_frescura
    min_fresco = pos_min >= umbral_frescura

    # Contar repeticiones recientes (evitar consolidación)
    if len(precios) >= ventana_rep:
        ultimos_n = precios[-ventana_rep:]
        conteo_maximos = sum(1 for p in ultimos_n if p == max_50)
        conteo_minimos = sum(1 for p in ultimos_n if p == min_50)
    else:
        conteo_maximos = sum(1 for p in precios if p == max_50)
        conteo_minimos = sum(1 for p in precios if p == min_50)

    # ===== REGLA (TU PEDIDO): REVERSIÓN INMEDIATA =====
    # "Se llegó al máximo" en el tick anterior y el tick actual es menor => VENTA.
    # "Se llegó al mínimo" en el tick anterior y el tick actual es mayor => COMPRA.
    if estado_actual == "IDLE":
        n = len(precios)
        # Requisito nuevo (tu pedido):
        # - El extremo (MAX/MIN) ocurrió hace 2 ticks (n-3)
        # - Hay 2 ticks consecutivos de reversa (p[n-2] y p[n-1])
        # - El segundo tick NO hace nuevo extremo (lo garantizamos con idx_max/idx_min == n-3)
        # - El retroceso desde el extremo supera el promedio reciente (y el min_rev anti-continuación)
        #
        # Nota: disparar la entrada en el segundo tick de reversa reduce falsos positivos.
        max_en_t_2 = (n >= 3) and (int(idx_max) == (n - 3))
        min_en_t_2 = (n >= 3) and (int(idx_min) == (n - 3))
        required_move = max(float(min_rev), float(avg_abs_delta) * float(avg_delta_factor))

        # Venta (PUT): tocó MAX hace 2 ticks y ahora hay 2 ticks bajistas consecutivos.
        if (
            permitir_put
            and max_fresco
            and (conteo_maximos <= max_rep)
            and max_en_t_2
            and (float(precios[-2]) < float(precios[-3]))
            and (float(precios[-1]) < float(precios[-2]))
            and (float(precio_actual) < float(max_50))
            and ((float(max_50) - float(precio_actual)) >= float(required_move))
        ):
            return ResultadoSenalExtremos(
                decision="VENTA",
                razon=(
                    f"Reversión 2-ticks desde MAX: idx_max={idx_max} "
                    f"p-2={float(precios[-3]):.3f} p-1={float(precios[-2]):.3f} p={float(precios[-1]):.3f} "
                    f"max={float(max_50):.3f} ahora={float(precio_actual):.3f} "
                    f"req_move={float(required_move):.5f} (min_rev={float(min_rev):.5f}, avgΔ={float(avg_abs_delta):.5f}*{float(avg_delta_factor):.2f})"
                ),
                precio_entrada_sugerido=float(precio_actual),
            )

        # Compra (CALL): tocó MIN hace 2 ticks y ahora hay 2 ticks alcistas consecutivos.
        if (
            permitir_call
            and min_fresco
            and (conteo_minimos <= max_rep)
            and min_en_t_2
            and (float(precios[-2]) > float(precios[-3]))
            and (float(precios[-1]) > float(precios[-2]))
            and (float(precio_actual) > float(min_50))
            and ((float(precio_actual) - float(min_50)) >= float(required_move))
        ):
            return ResultadoSenalExtremos(
                decision="COMPRA",
                razon=(
                    f"Reversión 2-ticks desde MIN: idx_min={idx_min} "
                    f"p-2={float(precios[-3]):.3f} p-1={float(precios[-2]):.3f} p={float(precios[-1]):.3f} "
                    f"min={float(min_50):.3f} ahora={float(precio_actual):.3f} "
                    f"req_move={float(required_move):.5f} (min_rev={float(min_rev):.5f}, avgΔ={float(avg_abs_delta):.5f}*{float(avg_delta_factor):.2f})"
                ),
                precio_entrada_sugerido=float(precio_actual),
            )

    # ===== NO HAY SEÑAL =====
    return ResultadoSenalExtremos(
        decision="NO_OPERAR",
        razon="No se cumplen condiciones para operar",
    )
