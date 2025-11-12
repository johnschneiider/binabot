from rest_framework import serializers


class NotificacionManualSerializer(serializers.Serializer):
    mensaje = serializers.CharField()
    numeros = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )

