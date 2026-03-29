from __future__ import annotations

from django.urls import path

from . import views

app_name = "gestion_riesgo"

urlpatterns = [
    path("panel/", views.dashboard, name="dashboard"),
    path("panel/eurusd/", views.dashboard_eurusd, name="dashboard_eurusd"),
    path("panel/binance/", views.dashboard_binance, name="dashboard_binance"),
    path("api/estado/", views.estado_json, name="estado_json"),
    path("api/estado_eurusd/", views.estado_eurusd_json, name="estado_eurusd_json"),
    path("api/estado_binance/", views.api_estado_binance, name="api_estado_binance"),
    path("api/binance/guardar/", views.api_guardar_operacion_binance, name="api_guardar_operacion_binance"),
    path("api/binance/tick/", views.api_guardar_tick_binance, name="api_guardar_tick_binance"),
    path("api/binance/sse/", views.sse_binance_stream, name="sse_binance_stream"),
    path("api/binance/config/", views.api_configuracion_estrategia, name="api_configuracion_estrategia"),
    path("api/balance/", views.balance_json, name="balance_json"),
    path("api/ticks/", views.ticks_json, name="ticks_json"),
    path("api/logs/", views.logs_json, name="logs_json"),
    path("api/ticks_colector/toggle/", views.ticks_colector_toggle, name="ticks_colector_toggle"),
    path("api/bot/toggle/", views.api_bot_toggle, name="api_bot_toggle"),
    path("api/sse/", views.sse_stream, name="sse_stream"),

    # Registro KYC
    path("registro/", views.registro_inversionista, name="registro"),
    path("portal/", views.portal_inversionista, name="portal_inversionista"),
    path("portal/api/fondo/", views.api_fondo_stats, name="api_fondo_stats"),
    path("portal/api/mis-rendimientos/", views.api_mis_rendimientos, name="api_mis_rendimientos"),
    path("portal/api/navbar/", views.api_navbar_balance, name="api_navbar_balance"),
    path("portal/api/moneda/", views.api_moneda, name="api_moneda"),
    path("portal/api/depositar/", views.api_depositar, name="api_depositar"),
    path("portal/api/retirar/", views.api_retirar, name="api_retirar"),
    path("portal/depositar/", views.depositar_view, name="depositar"),
    path("portal/retirar/", views.retirar_view, name="retirar"),
    path("inversionista/crear/", views.crear_inversionista, name="crear_inversionista"),
    path("inversionista/api/rendimiento/", views.api_rendimiento_inversionista, name="api_rendimiento_inversionista"),
    path("inversionista/liquidar/<int:inv_id>/", views.liquidar_inversionista, name="liquidar_inversionista"),
    path("admin/inversionistas/", views.admin_inversionistas, name="admin_inversionistas"),
]


