from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services import GestorBotCore

from .serializers import NotificacionManualSerializer
from .services import ServicioNotificaciones


class NotificacionManualView(APIView):
    """
    Endpoint para enviar una notificación manual por WhatsApp.
    """

    def post(self, request):
        serializer = NotificacionManualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        numeros = serializer.validated_data.get("numeros")
        mensaje = serializer.validated_data["mensaje"]

        servicio = ServicioNotificaciones()
        if numeros:
            servicio._enviar(mensaje, numeros)
        else:
            servicio._enviar(mensaje, servicio._destinatarios)

        return Response({"detalle": "Notificación enviada"}, status=status.HTTP_200_OK)


class NotificarEstadoBotView(APIView):
    """
    Envía una notificación con el estado actual del bot.
    """

    def post(self, request):
        gestor = GestorBotCore()
        configuracion = gestor.configuracion
        servicio = ServicioNotificaciones()

        servicio.notificar_inicio_operativa(configuracion)
        return Response({"detalle": "Estado enviado"}, status=status.HTTP_200_OK)
