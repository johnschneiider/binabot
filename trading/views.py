from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services import GestorBotCore

from .serializers import InicializarBalanceSerializer
from .services import MotorTrading


class EstadoTradingView(APIView):
    def get(self, request):
        gestor = GestorBotCore()
        estado = gestor.obtener_estado()
        data = {
            "balance_actual": str(estado.balance_actual),
            "meta_actual": str(estado.meta_actual),
            "stop_loss_actual": str(estado.stop_loss_actual),
            "estado": estado.estado,
            "activo_seleccionado": estado.activo_seleccionado,
            "perdida_acumulada": str(estado.perdida_acumulada),
            "ganancia_acumulada": str(estado.ganancia_acumulada),
            "en_operacion": estado.en_operacion,
            "pausado_desde": estado.pausado_desde,
            "pausa_finaliza": estado.pausa_finaliza,
            "mejor_horario": estado.mejor_horario,
        }
        return Response(data)


class InicializarBalanceView(APIView):
    def post(self, request):
        serializer = InicializarBalanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        balance = serializer.validated_data["balance_inicial"]
        gestor = GestorBotCore()
        configuracion = gestor.inicializar_balance(balance)
        return Response(
            {
                "detalle": "Balance inicial configurado",
                "balance_actual": str(configuracion.balance_actual),
                "meta_actual": str(configuracion.meta_actual),
                "stop_loss_actual": str(configuracion.stop_loss_actual),
            },
            status=status.HTTP_200_OK,
        )


class EjecutarOperacionView(APIView):
    def post(self, request):
        motor = MotorTrading()
        operacion = motor.ejecutar_ciclo()
        if not operacion:
            return Response(
                {"detalle": "No se ejecutó operación"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "detalle": "Operación ejecutada",
                "numero_contrato": operacion.numero_contrato,
                "resultado": operacion.resultado,
                "beneficio": str(operacion.beneficio),
            }
        )
