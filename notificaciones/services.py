from __future__ import annotations

from typing import Iterable

from django.conf import settings

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client


class ServicioNotificaciones:
    def __init__(self) -> None:
        self._client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self._from_number = settings.TWILIO_WHATSAPP_FROM
        self._destinatarios = settings.WHATSAPP_NUMEROS_ALERTA

    def _enviar(self, mensaje: str, destinatarios: Iterable[str]) -> None:
        for numero in destinatarios:
            if not numero:
                continue
            try:
                self._client.messages.create(
                    body=mensaje,
                    from_=self._from_number,
                    to=f"whatsapp:{numero}" if "whatsapp:" not in numero else numero,
                )
            except TwilioRestException:
                # En caso de error con un número específico, continuamos con el siguiente
                continue

    def notificar_inicio_operativa(self, configuracion) -> None:
        mensaje = (
            "🚀 El bot de trading ha iniciado su operativa.\n"
            f"Balance actual: {configuracion.balance_actual}\n"
            f"Stop loss dinámico (2%): {configuracion.stop_loss_actual}"
        )
        self._enviar(mensaje, self._destinatarios)

    def notificar_stop_loss(self, configuracion) -> None:
        mensaje = (
            "⛔️ Stop loss alcanzado. El bot entra en pausa de 24h.\n"
            f"Balance actual: {configuracion.balance_actual}\n"
            f"Pérdida acumulada: {configuracion.perdida_acumulada}\n"
            f"Reinicio previsto: {configuracion.pausa_finaliza}"
        )
        self._enviar(mensaje, self._destinatarios)

