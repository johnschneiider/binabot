from __future__ import annotations

from django.urls import path

from . import views

app_name = "gestion_riesgo"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/estado/", views.estado_json, name="estado_json"),
    path("api/balance/", views.balance_json, name="balance_json"),
    path("api/ticks/", views.ticks_json, name="ticks_json"),
    path("api/ticks_scatter/", views.ticks_scatter_json, name="ticks_scatter_json"),
    path("api/train_status/", views.train_status_json, name="train_status_json"),
    path("api/train/start/", views.train_start, name="train_start"),
    path("api/logs/", views.logs_json, name="logs_json"),
    path("api/ticks_colector/toggle/", views.ticks_colector_toggle, name="ticks_colector_toggle"),
    path("plots/scatter/", views.scatter_ticks_png, name="scatter_ticks_png"),
]


