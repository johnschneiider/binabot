"""
Módulo de interacción optimizada con PostgreSQL.
"""

from .cache_manager import (
    actualizar_tick_cache,
    obtener_ticks_cache,
    limpiar_cache_antiguo,
)

__all__ = [
    "actualizar_tick_cache",
    "obtener_ticks_cache",
    "limpiar_cache_antiguo",
]

