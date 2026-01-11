from __future__ import annotations

from django.urls import path

from . import views

app_name = "gestion_riesgo"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/estado/", views.estado_json, name="estado_json"),
    path("api/balance/", views.balance_json, name="balance_json"),
    path("api/ticks/", views.ticks_json, name="ticks_json"),
]


