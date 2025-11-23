from django.urls import path

from .views import HomeView, PanelPrincipalView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("bot-principal/", PanelPrincipalView.as_view(), name="panel-principal"),
]

