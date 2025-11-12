from django.urls import path

from .views import NotificacionManualView, NotificarEstadoBotView

urlpatterns = [
    path("enviar/", NotificacionManualView.as_view(), name="notificaciones-enviar"),
    path(
        "estado/",
        NotificarEstadoBotView.as_view(),
        name="notificaciones-estado-bot",
    ),
]

