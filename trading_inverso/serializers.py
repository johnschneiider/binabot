from rest_framework import serializers
from .models import OperacionInversa


class OperacionInversaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperacionInversa
        fields = [
            "id",
            "numero_contrato",
            "activo",
            "direccion",
            "resultado",
            "beneficio",
            "monto_invertido",
            "precio_entrada",
            "precio_cierre",
            "hora_inicio",
            "hora_fin",
            "operacion_principal_id",
        ]

