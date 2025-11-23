from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OperacionInversa, ConfiguracionBotInverso
from .services import GestorBotInverso
from .serializers import OperacionInversaSerializer


class DashboardInversoView(TemplateView):
    """Vista para el dashboard del bot inverso."""
    template_name = "trading_inverso/dashboard.html"


class EstadoBotInversoView(APIView):
    """Obtiene el estado actual del bot inverso."""
    
    def get(self, request):
        gestor = GestorBotInverso()
        estado = gestor.obtener_estado()
        return Response({
            "balance_actual": str(estado.balance_actual),
            "stop_loss_actual": str(estado.stop_loss_actual),
            "estado": estado.estado,
            "activo_seleccionado": estado.activo_seleccionado,
            "perdida_acumulada": str(estado.perdida_acumulada),
            "ganancia_acumulada": str(estado.ganancia_acumulada),
            "en_operacion": estado.en_operacion,
            "pausado_desde": estado.pausado_desde.isoformat() if estado.pausado_desde else None,
            "pausa_finaliza": estado.pausa_finaliza.isoformat() if estado.pausa_finaliza else None,
        })


class HistoricosInversosView(APIView):
    """Obtiene las últimas operaciones del bot inverso."""
    
    def get(self, request):
        recientes = OperacionInversa.objetos.reales().order_by('-hora_inicio')[:20]
        serializer = OperacionInversaSerializer(recientes, many=True)
        return Response(serializer.data)


class ReanudarBotInversoView(APIView):
    """Reanuda el bot inverso si está pausado."""
    
    def post(self, request):
        gestor = GestorBotInverso()
        config = gestor.configuracion
        
        if config.estado == config.Estado.OPERANDO:
            return Response({
                "mensaje": "El bot inverso ya está operando.",
                "estado": "operando"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        config.reanudar()
        return Response({
            "mensaje": "Bot inverso reanudado exitosamente.",
            "estado": "operando"
        })
