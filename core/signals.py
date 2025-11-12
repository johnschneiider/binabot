from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .models import ConfiguracionBot


@receiver(post_migrate)
def asegurar_configuracion_bot(sender, **kwargs):
    if sender.label != "core":
        return
    ConfiguracionBot.obtener()

