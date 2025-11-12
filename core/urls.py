from django.urls import path

from .views import PanelPrincipalView

urlpatterns = [
    path("", PanelPrincipalView.as_view(), name="panel-principal"),
]

