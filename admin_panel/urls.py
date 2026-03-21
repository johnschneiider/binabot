from django.urls import path
from . import views

app_name = "admin_panel"

urlpatterns = [
    path("login/", views.admin_login, name="login"),
    path("logout/", views.admin_logout, name="logout"),
    path("", views.admin_dashboard, name="dashboard"),
    path("cuentas/", views.admin_cuentas, name="cuentas"),
    path("operaciones/", views.admin_operaciones, name="operaciones"),
    path("suscripciones/", views.admin_suscripciones, name="suscripciones"),
    path("tenants/", views.admin_tenants, name="tenants"),
    path("logs/", views.admin_logs, name="logs"),
]
