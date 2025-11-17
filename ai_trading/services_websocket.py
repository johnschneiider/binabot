"""
Servicio para enviar actualizaciones del entrenamiento de IA en tiempo real.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from decimal import Decimal


def enviar_actualizacion_entrenamiento(tipo: str, datos: dict):
    """
    Envía una actualización del entrenamiento a través de WebSocket.
    
    Args:
        tipo: Tipo de actualización ('progreso_generacion', 'evaluacion_estrategia', 
              'estado_entrenamiento', 'nuevo_trade', etc.)
        datos: Diccionario con los datos de la actualización
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    
    try:
        payload = {
            "tipo": tipo,
            "timestamp": timezone.now().isoformat(),
            **datos
        }
        
        # Enviar al grupo del entrenamiento de IA
        async_to_sync(channel_layer.group_send)(
            "entrenamiento_ia_updates",
            {
                "type": "recibir_actualizacion_entrenamiento",
                "data": payload,
            }
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error al enviar actualización del entrenamiento: {e}", exc_info=True)


def enviar_progreso_generacion(
    generacion: int,
    total_generaciones: int,
    fitness_promedio: Decimal,
    fitness_mejor: Decimal,
    fitness_peor: Decimal,
    mejor_estrategia_nombre: str,
    mejor_estrategia_fitness: Decimal,
    tiempo_transcurrido: float,
):
    """Envía actualización de progreso de una generación."""
    enviar_actualizacion_entrenamiento(
        "progreso_generacion",
        {
            "generacion": generacion,
            "total_generaciones": total_generaciones,
            "fitness_promedio": float(fitness_promedio),
            "fitness_mejor": float(fitness_mejor),
            "fitness_peor": float(fitness_peor),
            "mejor_estrategia": {
                "nombre": mejor_estrategia_nombre,
                "fitness": float(mejor_estrategia_fitness),
            },
            "tiempo_transcurrido": tiempo_transcurrido,
        }
    )


def enviar_evaluacion_estrategia(
    estrategia_numero: int,
    total_estrategias: int,
    estrategia_nombre: str,
    fitness: Decimal,
):
    """Envía actualización de evaluación de una estrategia."""
    enviar_actualizacion_entrenamiento(
        "evaluacion_estrategia",
        {
            "estrategia_numero": estrategia_numero,
            "total_estrategias": total_estrategias,
            "estrategia_nombre": estrategia_nombre,
            "fitness": float(fitness),
        }
    )


def enviar_estado_entrenamiento(
    estado: str,
    mensaje: str = None,
    entrenamiento_id: int = None,
):
    """Envía actualización del estado del entrenamiento."""
    datos = {"estado": estado}
    if mensaje:
        datos["mensaje"] = mensaje
    if entrenamiento_id:
        datos["entrenamiento_id"] = entrenamiento_id
    
    enviar_actualizacion_entrenamiento("estado_entrenamiento", datos)


def enviar_nuevo_trade_ia(
    trade_id: int,
    estrategia_nombre: str,
    activo: str,
    direccion: str,
    resultado: str,
    beneficio: Decimal,
    reward: Decimal,
):
    """Envía actualización de un nuevo trade de IA."""
    enviar_actualizacion_entrenamiento(
        "nuevo_trade",
        {
            "trade_id": trade_id,
            "estrategia_nombre": estrategia_nombre,
            "activo": activo,
            "direccion": direccion,
            "resultado": resultado,
            "beneficio": float(beneficio),
            "reward": float(reward),
        }
    )

