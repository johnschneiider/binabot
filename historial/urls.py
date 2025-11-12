from django.urls import path

from .views import ExportarOperacionesCSVView, OperacionListView

urlpatterns = [
    path("operaciones/", OperacionListView.as_view(), name="historial-operaciones"),
    path(
        "operaciones/exportar/",
        ExportarOperacionesCSVView.as_view(),
        name="historial-exportar",
    ),
]

