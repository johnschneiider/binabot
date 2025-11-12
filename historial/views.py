import csv
from datetime import datetime

from django.http import HttpResponse
from rest_framework import generics
from rest_framework.views import APIView

from .models import Operacion
from .serializers import OperacionSerializer


class OperacionListView(generics.ListAPIView):
    serializer_class = OperacionSerializer

    def get_queryset(self):
        queryset = Operacion.objetos.all()
        tipo = self.request.query_params.get("tipo")
        if tipo == "reales":
            queryset = queryset.reales()
        elif tipo == "simuladas":
            queryset = queryset.simuladas()
        return queryset


class ExportarOperacionesCSVView(APIView):
    def get(self, request):
        queryset = Operacion.objetos.all()
        tipo = request.query_params.get("tipo")
        if tipo == "reales":
            queryset = queryset.reales()
        elif tipo == "simuladas":
            queryset = queryset.simuladas()

        respuesta = HttpResponse(content_type="text/csv")
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        respuesta["Content-Disposition"] = f'attachment; filename="operaciones_{fecha}.csv"'
        writer = csv.writer(respuesta)
        writer.writerow(
            [
                "Activo",
                "Direccion",
                "Precio entrada",
                "Precio cierre",
                "Monto invertido",
                "Confianza",
                "Resultado",
                "Numero contrato",
                "Hora inicio",
                "Hora fin",
                "Beneficio",
                "Es simulada",
            ]
        )

        for operacion in queryset:
            writer.writerow(
                [
                    operacion.activo,
                    operacion.direccion,
                    operacion.precio_entrada,
                    operacion.precio_cierre,
                    operacion.monto_invertido,
                    operacion.confianza,
                    operacion.resultado,
                    operacion.numero_contrato,
                    operacion.hora_inicio,
                    operacion.hora_fin,
                    operacion.beneficio,
                    operacion.es_simulada,
                ]
            )

        return respuesta
