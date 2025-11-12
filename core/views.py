from django.views.generic import TemplateView


class PanelPrincipalView(TemplateView):
    template_name = "core/panel.html"
