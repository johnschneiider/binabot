"""
Gestión profesional de riesgo dinámico.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from core.models import ConfiguracionBot
from trading.models import CooldownActivo, IndicadoresActivo


def calcular_monto_adaptativo(
    balance: Decimal,
    volatilidad: Decimal,
    riesgo_base: Decimal = Decimal("0.005"),  # 0.5% por defecto
    volatilidad_maxima: Decimal = Decimal("2.0"),
) -> Decimal:
    """
    Calcula el monto del trade adaptado a la volatilidad.
    
    Fórmula:
    monto = balance * riesgo_base * (1 - volatilidad_normalizada)
    
    Args:
        balance: Balance actual
        volatilidad: Volatilidad del activo
        riesgo_base: Porcentaje de riesgo base (default: 0.5%)
        volatilidad_maxima: Volatilidad máxima esperada
    
    Returns:
        Monto calculado para el trade
    """
    # Normalizar volatilidad (0-1)
    if volatilidad_maxima > 0:
        vol_norm = min(volatilidad / volatilidad_maxima, Decimal("1.0"))
    else:
        vol_norm = Decimal("0.0")
    
    # Reducir riesgo si la volatilidad es alta
    factor_riesgo = Decimal("1.0") - (vol_norm * Decimal("0.5"))  # Reducir hasta 50%
    
    monto = balance * riesgo_base * factor_riesgo
    
    # Asegurar mínimo y máximo razonables
    monto_minimo = balance * Decimal("0.001")  # Mínimo 0.1%
    monto_maximo = balance * Decimal("0.02")   # Máximo 2%
    
    monto = max(monto_minimo, min(monto, monto_maximo))
    
    return monto.quantize(Decimal("0.01"))


def verificar_cooldown(activo_id: int) -> bool:
    """
    Verifica si un activo está en cooldown.
    
    Args:
        activo_id: ID del activo
    
    Returns:
        True si puede operar, False si está en cooldown
    """
    cooldowns_activos = CooldownActivo.objects.filter(
        activo_id=activo_id,
        finaliza_en__gt=timezone.now(),
    )
    
    return not cooldowns_activos.exists()


def crear_cooldown(
    activo_id: int,
    motivo: str,
    duracion_minutos: int = 5,
) -> CooldownActivo:
    """
    Crea un cooldown para un activo.
    
    Args:
        activo_id: ID del activo
        motivo: Razón del cooldown (máximo 40 caracteres)
        duracion_minutos: Duración del cooldown en minutos
    
    Returns:
        Instancia de CooldownActivo creada
    """
    from core.models import ActivoPermitido
    
    activo = ActivoPermitido.objects.get(pk=activo_id)
    
    # Truncar motivo si es muy largo (asegurar máximo 40 caracteres)
    # PostgreSQL varying(40) se refiere a caracteres, no bytes
    motivo_str = str(motivo).strip()
    
    # Truncar a máximo 40 caracteres
    if len(motivo_str) > 40:
        motivo_truncado = motivo_str[:40]
    else:
        motivo_truncado = motivo_str
    
    # Validación final: asegurar que no esté vacío y que no exceda 40 caracteres
    if not motivo_truncado:
        motivo_truncado = "Cooldown activado"
    
    # Asegurar que no exceda 40 caracteres (validación final)
    motivo_truncado = motivo_truncado[:40]
    
    # Validación adicional: verificar longitud antes de crear
    if len(motivo_truncado) > 40:
        # Si por alguna razón aún excede, usar valor por defecto
        motivo_truncado = "Cooldown activado"
    
    try:
        cooldown = CooldownActivo.objects.create(
            activo=activo,
            motivo=motivo_truncado,
            finaliza_en=timezone.now() + timedelta(minutes=duracion_minutos),
        )
        return cooldown
    except Exception as e:
        # Si falla, intentar con motivo por defecto
        if motivo_truncado != "Cooldown activado":
            try:
                cooldown = CooldownActivo.objects.create(
                    activo=activo,
                    motivo="Cooldown activado",
                    finaliza_en=timezone.now() + timedelta(minutes=duracion_minutos),
                )
                return cooldown
            except Exception as e2:
                # Log del error original para debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.error(
                    f"Error al crear cooldown para activo {activo_id}. "
                    f"Motivo original: '{motivo}' (len={len(str(motivo))}), "
                    f"Motivo truncado: '{motivo_truncado}' (len={len(motivo_truncado)}). "
                    f"Error: {e}, Error2: {e2}"
                )
                raise
        else:
            raise


def verificar_limites_activo(
    activo_nombre: str,
    max_trades_por_ciclo: int = 1,
    periodo_minutos: int = 60,
) -> bool:
    """
    Verifica si un activo ha alcanzado el límite de trades en el período.
    
    Args:
        activo_nombre: Nombre del activo
        max_trades_por_ciclo: Máximo de trades permitidos
        periodo_minutos: Período de tiempo a considerar
    
    Returns:
        True si puede operar, False si alcanzó el límite
    """
    from historial.models import Operacion
    
    desde = timezone.now() - timedelta(minutes=periodo_minutos)
    
    trades_recientes = Operacion.objetos.reales().filter(
        activo=activo_nombre,
        hora_inicio__gte=desde,
    ).count()
    
    return trades_recientes < max_trades_por_ciclo


def detectar_micro_congestion(
    indicadores: IndicadoresActivo,
    umbral_variacion: Decimal = Decimal("0.01"),  # 0.01%
    umbral_frecuencia: int = 10,  # 10 ticks en poco tiempo
) -> bool:
    """
    Detecta si un activo está en estado de micro-congestión.
    
    Micro-congestión = baja variación + alta frecuencia de ticks.
    
    Args:
        indicadores: Indicadores del activo
        umbral_variacion: Variación mínima esperada
        umbral_frecuencia: Frecuencia máxima de ticks
    
    Returns:
        True si está en micro-congestión
    """
    # Baja variación
    baja_variacion = abs(indicadores.momentum_pct) < umbral_variacion
    
    # Alta frecuencia (muchos ticks analizados en poco tiempo)
    alta_frecuencia = indicadores.ticks_analizados > umbral_frecuencia
    
    return baja_variacion and alta_frecuencia

