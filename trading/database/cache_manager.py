"""
Gestión optimizada del cache de ticks en PostgreSQL.
"""
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from core.models import ActivoPermitido
from historial.models import Tick
from trading.models import TickCache


@transaction.atomic
def actualizar_tick_cache(activo: ActivoPermitido, max_ticks: int = 20) -> None:
    """
    Actualiza el cache de ticks para un activo.
    Mantiene solo los últimos N ticks.
    
    Args:
        activo: Activo a actualizar
        max_ticks: Número máximo de ticks a mantener
    """
    # Obtener los últimos ticks del historial
    ticks_recientes = (
        Tick.objects.filter(activo=activo.nombre)
        .order_by("-epoch")[:max_ticks]
    )
    
    if not ticks_recientes.exists():
        return
    
    # Eliminar cache antiguo
    TickCache.objects.filter(activo=activo).delete()
    
    # Crear nuevos registros en cache
    tick_caches = []
    for tick in ticks_recientes:
        # Convertir DateTimeField a epoch (segundos desde 1970)
        if isinstance(tick.epoch, (int, float)):
            epoch_value = int(tick.epoch)
        else:
            # Si es datetime, convertir a timestamp
            epoch_value = int(tick.epoch.timestamp())
        
        tick_caches.append(
            TickCache(
                activo=activo,
                precio=Decimal(str(tick.precio)),
                epoch=epoch_value,
            )
        )
    
    TickCache.objects.bulk_create(tick_caches)


def obtener_ticks_cache(
    activo: ActivoPermitido,
    cantidad: int = 20,
) -> List[Decimal]:
    """
    Obtiene los últimos N ticks de precio desde el cache.
    
    Args:
        activo: Activo a consultar
        cantidad: Número de ticks a obtener
    
    Returns:
        Lista de precios ordenados (más antiguo primero)
    """
    ticks = (
        TickCache.objects.filter(activo=activo)
        .order_by("epoch")[:cantidad]
    )
    
    return [tick.precio for tick in ticks]


def limpiar_cache_antiguo(dias_antiguedad: int = 1) -> int:
    """
    Limpia el cache de ticks más antiguos que N días.
    
    Args:
        dias_antiguedad: Días de antigüedad para considerar
    
    Returns:
        Número de registros eliminados
    """
    fecha_limite = timezone.now() - timedelta(days=dias_antiguedad)
    
    eliminados = TickCache.objects.filter(
        timestamp__lt=fecha_limite
    ).delete()[0]
    
    return eliminados


@transaction.atomic
def actualizar_indicadores_activo(
    activo: ActivoPermitido,
    indicadores_data: dict,
):
    """
    Actualiza o crea los indicadores de un activo.
    
    Args:
        activo: Activo a actualizar
        indicadores_data: Diccionario con los valores de indicadores
    
    Returns:
        Instancia de IndicadoresActivo
    """
    from trading.models import IndicadoresActivo
    
    indicadores, _ = IndicadoresActivo.objects.update_or_create(
        activo=activo,
        defaults=indicadores_data,
    )
    
    return indicadores

