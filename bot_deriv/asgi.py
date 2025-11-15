"""
ASGI config for bot_deriv project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf import settings
from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bot_deriv.settings")

django_asgi_app = get_asgi_application()

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

# Cargar rutas WebSocket de integracion_deriv
try:
    from integracion_deriv.routing import (
        websocket_urlpatterns as deriv_websocket_patterns,
    )
except Exception as exc:
    deriv_websocket_patterns = []
    import logging

    logging.getLogger(__name__).warning(
        "No se pudieron cargar las rutas websocket de deriv: %s", exc, exc_info=True
    )

# Cargar rutas WebSocket del dashboard
try:
    from dashboard.routing import (
        websocket_urlpatterns as dashboard_websocket_patterns,
    )
except Exception as exc:
    dashboard_websocket_patterns = []
    import logging

    logging.getLogger(__name__).warning(
        "No se pudieron cargar las rutas websocket del dashboard: %s", exc, exc_info=True
    )

# Combinar todas las rutas WebSocket
all_websocket_patterns = deriv_websocket_patterns + dashboard_websocket_patterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(all_websocket_patterns)
        ),
    }
)
