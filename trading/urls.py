from django.urls import path

from .views import EjecutarOperacionView, EstadoTradingView, InicializarBalanceView

urlpatterns = [
    path("estado/", EstadoTradingView.as_view(), name="trading-estado"),
    path("inicializar/", InicializarBalanceView.as_view(), name="trading-inicializar"),
    path("ejecutar/", EjecutarOperacionView.as_view(), name="trading-ejecutar"),
]

