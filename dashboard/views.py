from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services import GestorBotCore
from historial.models import Operacion, Tick
from historial.serializers import OperacionSerializer


class WinrateView(APIView):
    def get(self, request):
        queryset = Operacion.objetos.reales()
        total = queryset.count()
        ganadas = queryset.ganadas().count()
        winrate = (ganadas / total * 100) if total else 0
        return Response(
            {
                "total_operaciones": total,
                "ganadas": ganadas,
                "winrate": round(winrate, 2),
            }
        )


class EstadoBotView(APIView):
    def get(self, request):
        gestor = GestorBotCore()
        estado = gestor.obtener_estado()
        return Response(
            {
                "estado": estado.estado,
                "balance_actual": str(estado.balance_actual),
                "meta_actual": str(estado.meta_actual),
                "stop_loss_actual": str(estado.stop_loss_actual),
                "perdida_acumulada": str(estado.perdida_acumulada),
                "ganancia_acumulada": str(estado.ganancia_acumulada),
                "activo_seleccionado": estado.activo_seleccionado,
            }
        )


class HistoricosView(APIView):
    def get(self, request):
        recientes = Operacion.objetos.reales()[:20]
        serializer = OperacionSerializer(recientes, many=True)
        return Response(serializer.data)


class BalanceView(APIView):
    def get(self, request):
        gestor = GestorBotCore()
        estado = gestor.obtener_estado()
        return Response(
            {
                "balance_actual": str(estado.balance_actual),
                "meta_actual": str(estado.meta_actual),
                "stop_loss_actual": str(estado.stop_loss_actual),
            }
        )


class EstadisticasCallPutView(APIView):
    def get(self, request):
        queryset = Operacion.objetos.reales()
        ganadas_call = queryset.filter(
            direccion=Operacion.Direccion.CALL, resultado=Operacion.Resultado.GANADA
        ).count()
        ganadas_put = queryset.filter(
            direccion=Operacion.Direccion.PUT, resultado=Operacion.Resultado.GANADA
        ).count()
        perdidas_call = queryset.filter(
            direccion=Operacion.Direccion.CALL, resultado=Operacion.Resultado.PERDIDA
        ).count()
        perdidas_put = queryset.filter(
            direccion=Operacion.Direccion.PUT, resultado=Operacion.Resultado.PERDIDA
        ).count()

        return Response(
            {
                "ganadas_call": ganadas_call,
                "ganadas_put": ganadas_put,
                "perdidas_call": perdidas_call,
                "perdidas_put": perdidas_put,
            }
        )


class TemporizadorView(APIView):
    def get(self, request):
        gestor = GestorBotCore()
        estado = gestor.obtener_estado()
        if estado.estado != gestor.configuracion.Estado.PAUSADO or not estado.pausado_desde:
            return Response(
                {"pausado": False, "tiempo_detencion": None, "reactivacion": None}
            )

        ahora = timezone.now()
        tiempo_detencion = ahora - estado.pausado_desde
        restante = None
        if estado.pausa_finaliza:
            restante = estado.pausa_finaliza - ahora
            if restante < timedelta(0):
                restante = timedelta(0)

        return Response(
            {
                "pausado": True,
                "tiempo_detencion": tiempo_detencion.total_seconds(),
                "reactivacion": estado.pausa_finaliza,
                "tiempo_restante": restante.total_seconds() if restante else None,
                "mejor_horario": estado.mejor_horario,
            }
        )


class TickAnaliticaView(APIView):
    def get(self, request):
        activo = request.query_params.get("activo")
        limite = int(request.query_params.get("limite", 200))

        if not activo:
            return Response(
                {"detalle": "Debe indicar el parámetro 'activo'."},
                status=400,
            )

        ticks = list(Tick.objects.filter(activo=activo).order_by("-epoch")[:limite])
        if not ticks:
            return Response(
                {
                    "activo": activo,
                    "total": 0,
                    "detalle": "No hay ticks registrados para este activo.",
                },
                status=200,
            )

        precios = [tick.precio for tick in ticks]
        maximo = max(precios)
        minimo = min(precios)
        promedio = sum(precios) / len(precios)
        ultimo = ticks[0]
        primero = ticks[-1]

        return Response(
            {
                "activo": activo,
                "total": len(precios),
                "limite": limite,
                "ultimo_tick": {
                    "precio": str(ultimo.precio),
                    "epoch": ultimo.epoch,
                    "pip_size": ultimo.pip_size,
                },
                "primer_tick": {
                    "precio": str(primero.precio),
                    "epoch": primero.epoch,
                },
                "estadisticas": {
                    "maximo": str(maximo),
                    "minimo": str(minimo),
                    "promedio": str(promedio),
                    "variacion": str(ultimo.precio - primero.precio),
                },
            }
        )
