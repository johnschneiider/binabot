from django.urls import path
from .views import DashboardInversoView, EstadoBotInversoView, HistoricosInversosView, ReanudarBotInversoView

app_name = "trading_inverso"

urlpatterns = [
    path("", DashboardInversoView.as_view(), name="dashboard"),
    path("estado/", EstadoBotInversoView.as_view(), name="estado"),
    path("historicos/", HistoricosInversosView.as_view(), name="historicos"),
    path("reanudar/", ReanudarBotInversoView.as_view(), name="reanudar"),
]

