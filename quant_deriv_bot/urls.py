from __future__ import annotations

from django.contrib import admin
from django.urls import include
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("subscriptions.urls")),
    path("", include("pages.urls")),
    path("", include("gestion_riesgo.urls")),
    path("", include("trading.urls")),
    path("admin-panel/", include("admin_panel.urls")),
]


