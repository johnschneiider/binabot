from decimal import Decimal

from rest_framework import serializers


class InicializarBalanceSerializer(serializers.Serializer):
    balance_inicial = serializers.DecimalField(max_digits=12, decimal_places=2)


class OperacionManualSerializer(serializers.Serializer):
    activo = serializers.CharField(max_length=80, required=False)
    direccion = serializers.ChoiceField(
        choices=["CALL", "PUT"], required=False, allow_null=True
    )
    monto = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    confianza = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )

