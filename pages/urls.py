from django.views.generic import TemplateView
from django.urls import path

app_name = "pages"

urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/index.html"), name="index"),
    path("planes/", TemplateView.as_view(template_name="pages/planes.html"), name="planes"),
]
