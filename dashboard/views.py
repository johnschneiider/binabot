from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services import GestorBotCore
from historial.models import Operacion, Tick
from historial.serializers import OperacionSerializer
from .services_estado import EstadoServiciosService


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
        config = gestor.configuracion
        return Response(
            {
                "estado": estado.estado,
                "balance_actual": str(estado.balance_actual),
                "stop_loss_actual": str(estado.stop_loss_actual),
                "perdida_acumulada": str(estado.perdida_acumulada),
                "ganancia_acumulada": str(estado.ganancia_acumulada),
                "activo_seleccionado": estado.activo_seleccionado,
                "modo_inverso": config.modo_inverso,
            }
        )


class HistoricosView(APIView):
    def get(self, request):
        # Ordenar por hora_inicio descendente para mostrar las más recientes primero
        recientes = Operacion.objetos.reales().order_by("-hora_inicio")[:20]
        serializer = OperacionSerializer(recientes, many=True)
        return Response(serializer.data)


class BalanceView(APIView):
    def get(self, request):
        gestor = GestorBotCore()
        estado = gestor.obtener_estado()
        return Response(
            {
                "balance_actual": str(estado.balance_actual),
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


class EstadoServiciosView(APIView):
    """
    Vista para obtener el estado de los servicios systemd del bot.
    """
    def get(self, request):
        try:
            resumen = EstadoServiciosService.obtener_resumen_estado()
            return Response(resumen)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error al obtener estado de servicios: {e}", exc_info=True)
            return Response(
                {
                    "error": "No se pudo verificar el estado de los servicios",
                    "detalle": str(e),
                },
                status=500,
            )


class ModoInversoView(APIView):
    """
    Vista para obtener y actualizar el modo inverso del bot.
    """
    def get(self, request):
        gestor = GestorBotCore()
        config = gestor.configuracion
        return Response({"modo_inverso": config.modo_inverso})
    
    def post(self, request):
        gestor = GestorBotCore()
        config = gestor.configuracion
        modo_inverso = request.data.get("modo_inverso", False)
        config.modo_inverso = bool(modo_inverso)
        config.save(update_fields=["modo_inverso"])
        return Response({
            "modo_inverso": config.modo_inverso,
            "mensaje": "Modo inverso activado" if config.modo_inverso else "Modo inverso desactivado"
        })


class ReiniciarServiciosView(APIView):
    """
    Vista para reiniciar los servicios systemd del bot.
    """
    def post(self, request):
        import subprocess
        import logging
        
        logger = logging.getLogger(__name__)
        servicios = [
            "binabot-loop.service",
            "binabot-ticks.service",
        ]
        
        resultados = {}
        errores = []
        
        for servicio in servicios:
            try:
                # Reiniciar el servicio
                resultado = subprocess.run(
                    ["sudo", "systemctl", "restart", servicio],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                
                if resultado.returncode == 0:
                    resultados[servicio] = "reiniciado"
                else:
                    resultados[servicio] = f"error: {resultado.stderr}"
                    errores.append(f"{servicio}: {resultado.stderr}")
                    
            except subprocess.TimeoutExpired:
                resultados[servicio] = "timeout"
                errores.append(f"{servicio}: timeout al reiniciar")
            except FileNotFoundError:
                # En Windows o sin sudo, retornar error
                return Response(
                    {
                        "error": "No se puede reiniciar servicios (solo disponible en Linux con sudo)",
                        "detalle": "Este endpoint requiere ejecutarse en un servidor Linux con permisos sudo.",
                    },
                    status=500,
                )
            except Exception as e:
                resultados[servicio] = f"error: {str(e)}"
                errores.append(f"{servicio}: {str(e)}")
                logger.error(f"Error reiniciando {servicio}: {e}", exc_info=True)
        
        if errores:
            return Response(
                {
                    "mensaje": "Algunos servicios tuvieron errores al reiniciar",
                    "resultados": resultados,
                    "errores": errores,
                },
                status=207,  # Multi-Status
            )
        
        return Response(
            {
                "mensaje": "Servicios reiniciados correctamente",
                "resultados": resultados,
            }
        )
