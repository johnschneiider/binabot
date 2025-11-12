from django.urls import path

from .consumers import DerivStatusConsumer

websocket_urlpatterns = [
    path("ws/deriv/estado/", DerivStatusConsumer.as_asgi()),
]

