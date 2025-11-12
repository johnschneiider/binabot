from rest_framework import serializers

from .models import Operacion


class OperacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operacion
        fields = [
            "id",
            "activo",
            "direccion",
            "precio_entrada",
            "precio_cierre",
            "monto_invertido",
            "confianza",
            "resultado",
            "numero_contrato",
            "hora_inicio",
            "hora_fin",
            "beneficio",
            "es_simulada",
        ]

