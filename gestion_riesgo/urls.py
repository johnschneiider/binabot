from __future__ import annotations

from django.urls import path

from . import views

app_name = "gestion_riesgo"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("eurusd/", views.dashboard_eurusd, name="dashboard_eurusd"),
    path("api/estado/", views.estado_json, name="estado_json"),
    path("api/estado_eurusd/", views.estado_eurusd_json, name="estado_eurusd_json"),
    path("api/balance/", views.balance_json, name="balance_json"),
    path("api/ticks/", views.ticks_json, name="ticks_json"),
    path("api/logs/", views.logs_json, name="logs_json"),
    path("api/ticks_colector/toggle/", views.ticks_colector_toggle, name="ticks_colector_toggle"),
    path("api/sse/", views.sse_stream, name="sse_stream"),
]


