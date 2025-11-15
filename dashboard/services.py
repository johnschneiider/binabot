"""
Servicio para enviar actualizaciones del dashboard en tiempo real.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from core.services import GestorBotCore
from historial.models import Operacion


def enviar_actualizacion_dashboard():
    """
    Envía una actualización completa del dashboard a través de WebSocket.
    Se ejecuta cada 10 segundos o cuando hay eventos importantes.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    
    try:
        gestor = GestorBotCore()
        estado = gestor.obtener_estado()
        
        # Obtener estadísticas
        operaciones = Operacion.objetos.reales()
        total_operaciones = operaciones.count()
        ganadas = operaciones.ganadas().count()
        winrate = (ganadas / total_operaciones * 100) if total_operaciones else 0
        
        # Estadísticas CALL/PUT
        ganadas_call = operaciones.filter(
            direccion=Operacion.Direccion.CALL, 
            resultado=Operacion.Resultado.GANADA
        ).count()
        ganadas_put = operaciones.filter(
            direccion=Operacion.Direccion.PUT, 
            resultado=Operacion.Resultado.GANADA
        ).count()
        perdidas_call = operaciones.filter(
            direccion=Operacion.Direccion.CALL, 
            resultado=Operacion.Resultado.PERDIDA
        ).count()
        perdidas_put = operaciones.filter(
            direccion=Operacion.Direccion.PUT, 
            resultado=Operacion.Resultado.PERDIDA
        ).count()
        
        # Últimas operaciones
        ultimas_operaciones = list(operaciones[:20])
        from historial.serializers import OperacionSerializer
        operaciones_data = OperacionSerializer(ultimas_operaciones, many=True).data
        
        # Temporizador
        temporizador_data = {
            "pausado": False,
            "tiempo_detencion": None,
            "reactivacion": None,
            "tiempo_restante": None,
        }
        
        if estado.estado == gestor.configuracion.Estado.PAUSADO and estado.pausado_desde:
            ahora = timezone.now()
            tiempo_detencion = ahora - estado.pausado_desde
            restante = None
            if estado.pausa_finaliza:
                restante = estado.pausa_finaliza - ahora
                if restante.total_seconds() < 0:
                    restante = None
            
            temporizador_data = {
                "pausado": True,
                "tiempo_detencion": tiempo_detencion.total_seconds(),
                "reactivacion": estado.pausa_finaliza.isoformat() if estado.pausa_finaliza else None,
                "tiempo_restante": restante.total_seconds() if restante else None,
                "mejor_horario": estado.mejor_horario.isoformat() if estado.mejor_horario else None,
            }
        
        # Preparar datos de actualización
        datos = {
            "tipo": "actualizacion_completa",
            "timestamp": timezone.now().isoformat(),
            "estado": {
                "estado": estado.estado,
                "balance_actual": str(estado.balance_actual),
                "meta_actual": str(estado.meta_actual),
                "stop_loss_actual": str(estado.stop_loss_actual),
                "perdida_acumulada": str(estado.perdida_acumulada),
                "ganancia_acumulada": str(estado.ganancia_acumulada),
                "activo_seleccionado": estado.activo_seleccionado,
                "en_operacion": estado.en_operacion,
            },
            "winrate": {
                "total_operaciones": total_operaciones,
                "ganadas": ganadas,
                "winrate": round(winrate, 2),
            },
            "estadisticas": {
                "ganadas_call": ganadas_call,
                "ganadas_put": ganadas_put,
                "perdidas_call": perdidas_call,
                "perdidas_put": perdidas_put,
            },
            "operaciones": operaciones_data,
            "temporizador": temporizador_data,
        }
        
        # Enviar al grupo del dashboard
        async_to_sync(channel_layer.group_send)(
            "dashboard_updates",
            {
                "type": "recibir_actualizacion",
                "data": datos,
            }
        )
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error al enviar actualización del dashboard: {e}", exc_info=True)

