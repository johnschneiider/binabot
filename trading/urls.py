from django.urls import path
from . import views

urlpatterns = [
    path("panel/trading/", views.dashboard, name="dashboard"),
    path("api/trading/guardar/", views.api_guardar_operacion, name="api_guardar_operacion"),
    path("api/trading/tick/", views.api_guardar_tick, name="api_guardar_tick"),
    path("api/trading/sse/", views.sse_trading_stream, name="sse_trading_stream"),
    path("api/trading/config/", views.api_configuracion, name="api_configuracion"),
]
