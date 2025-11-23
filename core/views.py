from django.views.generic import TemplateView


class HomeView(TemplateView):
    """Vista para la página home que muestra ambos bots."""
    template_name = "home.html"


class PanelPrincipalView(TemplateView):
    """Vista para el panel principal del bot."""
    template_name = "core/panel.html"
