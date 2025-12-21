from __future__ import annotations

from django.contrib import admin
from django.urls import include
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("gestion_riesgo.urls")),
]


