"""Rutas WebSocket para el entrenamiento de IA."""
from django.urls import path

from .consumers import EntrenamientoIAConsumer

websocket_urlpatterns = [
    path("ws/ai/entrenamiento/", EntrenamientoIAConsumer.as_asgi()),
]

