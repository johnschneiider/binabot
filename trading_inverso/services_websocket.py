"""
Servicio para enviar actualizaciones del bot inverso en tiempo real.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import OperacionInversa, ConfiguracionBotInverso
from .services import GestorBotInverso
from .serializers import OperacionInversaSerializer


def enviar_actualizacion_bot_inverso():
    """
    Envía una actualización completa del bot inverso a través de WebSocket.
    Se ejecuta cada 10 segundos o cuando hay eventos importantes.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    
    try:
        gestor = GestorBotInverso()
        # Sincronizar balance desde Deriv antes de obtener el estado
        gestor.sincronizar_balance_desde_api()
        estado = gestor.obtener_estado()
        
        # Obtener estadísticas
        operaciones = OperacionInversa.objetos.reales()
        total_operaciones = operaciones.count()
        ganadas = operaciones.ganadas().count()
        winrate = (ganadas / total_operaciones * 100) if total_operaciones else 0
        
        # Últimas operaciones (ordenadas por hora_inicio descendente)
        ultimas_operaciones = list(operaciones.order_by('-hora_inicio')[:20])
        operaciones_data = OperacionInversaSerializer(ultimas_operaciones, many=True).data
        
        # Preparar datos de actualización
        datos = {
            "tipo": "actualizacion_completa",
            "timestamp": timezone.now().isoformat(),
            "estado": {
                "estado": estado.estado,
                "balance_actual": str(estado.balance_actual),
                "stop_loss_actual": str(estado.stop_loss_actual),
                "perdida_acumulada": str(estado.perdida_acumulada),
                "ganancia_acumulada": str(estado.ganancia_acumulada),
                "activo_seleccionado": estado.activo_seleccionado,
                "en_operacion": estado.en_operacion,
                "pausado_desde": estado.pausado_desde.isoformat() if estado.pausado_desde else None,
                "pausa_finaliza": estado.pausa_finaliza.isoformat() if estado.pausa_finaliza else None,
            },
            "winrate": {
                "total_operaciones": total_operaciones,
                "ganadas": ganadas,
                "winrate": round(winrate, 2),
            },
            "operaciones": operaciones_data,
        }
        
        # Enviar actualización al grupo
        async_to_sync(channel_layer.group_send)(
            "deriv_estado_inverso",
            {
                "type": "recibir_evento_deriv_inverso",
                "data": datos,
            }
        )
        
    except Exception as e:
        print(f"Error enviando actualizaciones del bot inverso: {e}")

