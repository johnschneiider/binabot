from datetime import timedelta

from django.db.models import Max
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from historial.models import Operacion
from historial.serializers import OperacionSerializer

from .models import ResultadoHorarioSimulacion
from .services import SimuladorHorariosService


class ResultadosSimulacionView(APIView):
    def get(self, request):
        fecha_reciente = ResultadoHorarioSimulacion.objects.aggregate(
            reciente=Max("fecha_calculo")
        ).get("reciente")

        resumen = []
        operaciones = []

        if fecha_reciente:
            resultados = (
                ResultadoHorarioSimulacion.objects.filter(fecha_calculo=fecha_reciente)
                .order_by("-winrate", "-total_operaciones")
                .values(
                    "hora_inicio",
                    "total_operaciones",
                    "operaciones_ganadas",
                    "operaciones_perdidas",
                    "winrate",
                )
            )
            resumen = [
                {
                    "hora_inicio": fila["hora_inicio"].strftime("%H:%M"),
                    "total_operaciones": fila["total_operaciones"],
                    "operaciones_ganadas": fila["operaciones_ganadas"],
                    "operaciones_perdidas": fila["operaciones_perdidas"],
                    "winrate": float(fila["winrate"]),
                }
                for fila in resultados
            ]

            inicio_busqueda = fecha_reciente - timedelta(hours=24)
            operaciones_qs = (
                Operacion.objetos.simuladas()
                .filter(hora_inicio__gte=inicio_busqueda)
                .order_by("-hora_inicio")[:200]
            )
            operaciones = OperacionSerializer(operaciones_qs, many=True).data

        return Response(
            {"resumen": resumen, "operaciones": operaciones},
            status=status.HTTP_200_OK,
        )


class EjecutarSimulacionView(APIView):
    def post(self, request):
        simulador = SimuladorHorariosService()
        resultado = simulador.ejecutar()
        if not resultado:
            return Response(
                {
                    "detalle": "No se pudo ejecutar la simulación (faltan ticks recientes o activos habilitados)."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "hora_optima": resultado.hora.strftime("%H:%M"),
                "winrate": float(resultado.winrate),
                "total_operaciones": resultado.total_operaciones,
                "ganadas": resultado.ganadas,
                "perdidas": resultado.perdidas,
            },
            status=status.HTTP_200_OK,
        )
