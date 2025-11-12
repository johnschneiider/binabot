from django.db.models import Max
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ResultadoHorarioSimulacion
from .services import SimuladorHorariosService


class ResultadosSimulacionView(APIView):
    def get(self, request):
        fecha_reciente = ResultadoHorarioSimulacion.objects.aggregate(
            reciente=Max("fecha_calculo")
        ).get("reciente")
        if not fecha_reciente:
            return Response([], status=status.HTTP_200_OK)

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
        data = [
            {
                "hora_inicio": fila["hora_inicio"].strftime("%H:%M"),
                "total_operaciones": fila["total_operaciones"],
                "operaciones_ganadas": fila["operaciones_ganadas"],
                "operaciones_perdidas": fila["operaciones_perdidas"],
                "winrate": float(fila["winrate"]),
            }
            for fila in resultados
        ]
        return Response(data, status=status.HTTP_200_OK)


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
