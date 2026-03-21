from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = "subscriptions"

router = DefaultRouter()
router.register(r"planes", views.PlanViewSet, basename="planes")
router.register(r"suscripciones", views.SuscripcionViewSet, basename="suscripciones")
router.register(r"tenants", views.TenantViewSet, basename="tenants")
router.register(r"audit-logs", views.LogAuditoriaViewSet, basename="audit-logs")

urlpatterns = [
    path("", include(router.urls)),
    
    # Autenticacion
    path("auth/csrf/", views.CsrfTokenView.as_view(), name="csrf-token"),
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/profile/", views.ProfileView.as_view(), name="profile"),
    path("auth/cambiar-password/", views.CambioPasswordView.as_view(), name="cambiar-password"),
    
    # Health check
    path("health/", views.health_check, name="health-check"),
]
