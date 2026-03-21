from django.views.generic import TemplateView
from django.urls import path

app_name = "pages"

urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/index.html"), name="index"),
]
