from django.urls import path

from .views import EjecutarSimulacionView, ResultadosSimulacionView

urlpatterns = [
    path("resultados/", ResultadosSimulacionView.as_view(), name="simulacion-resultados"),
    path("ejecutar/", EjecutarSimulacionView.as_view(), name="simulacion-ejecutar"),
]

