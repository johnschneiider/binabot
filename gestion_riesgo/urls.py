from __future__ import annotations

from django.urls import path

from . import views

app_name = "gestion_riesgo"

urlpatterns = [
    path("panel/", views.dashboard, name="dashboard"),
    path("panel/eurusd/", views.dashboard_eurusd, name="dashboard_eurusd"),
    path("api/estado/", views.estado_json, name="estado_json"),
    path("api/estado_eurusd/", views.estado_eurusd_json, name="estado_eurusd_json"),
    path("api/balance/", views.balance_json, name="balance_json"),
    path("api/ticks/", views.ticks_json, name="ticks_json"),
    path("api/logs/", views.logs_json, name="logs_json"),
    path("api/ticks_colector/toggle/", views.ticks_colector_toggle, name="ticks_colector_toggle"),
    path("api/sse/", views.sse_stream, name="sse_stream"),

    # Portal del Inversionista
    path("inversionista/", views.portal_inversionista, name="portal_inversionista"),
    path("inversionista/crear/", views.crear_inversionista, name="crear_inversionista"),
    path("inversionista/api/rendimiento/", views.api_rendimiento_inversionista, name="api_rendimiento_inversionista"),
    path("inversionista/liquidar/<int:inv_id>/", views.liquidar_inversionista, name="liquidar_inversionista"),
    path("admin/inversionistas/", views.admin_inversionistas, name="admin_inversionistas"),
]


