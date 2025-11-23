"""Rutas WebSocket para el bot inverso."""
from django.urls import path

from .consumers import BotInversoConsumer

websocket_urlpatterns = [
    path("ws/bot-inverso/", BotInversoConsumer.as_asgi()),
]

