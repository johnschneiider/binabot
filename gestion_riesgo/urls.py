from __future__ import annotations

from django.urls import path

from . import views

app_name = "gestion_riesgo"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/estado/", views.estado_json, name="estado_json"),
]


