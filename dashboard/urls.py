from django.urls import path

from .views import (
    BalanceView,
    EstadoBotView,
    EstadoServiciosView,
    EstadisticasCallPutView,
    HistoricosView,
    ModoInversoView,
    TemporizadorView,
    TickAnaliticaView,
    WinrateView,
)

urlpatterns = [
    path("winrate/", WinrateView.as_view(), name="dashboard-winrate"),
    path("estado/", EstadoBotView.as_view(), name="dashboard-estado"),
    path("historicos/", HistoricosView.as_view(), name="dashboard-historicos"),
    path("balance/", BalanceView.as_view(), name="dashboard-balance"),
    path(
        "estadisticas-call-put/",
        EstadisticasCallPutView.as_view(),
        name="dashboard-estadisticas-call-put",
    ),
    path("temporizador/", TemporizadorView.as_view(), name="dashboard-temporizador"),
    path("ticks/", TickAnaliticaView.as_view(), name="dashboard-ticks"),
    path("estado-servicios/", EstadoServiciosView.as_view(), name="dashboard-estado-servicios"),
    path("modo-inverso/", ModoInversoView.as_view(), name="dashboard-modo-inverso"),
]

