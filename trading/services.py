from __future__ import annotations

import random
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import ActivoPermitido
from core.services import GestorBotCore
from historial.models import Operacion
from integracion_deriv.client import obtener_ticks_history_sync, operar_contrato_sync
from trading.utils import priorizar_activos_por_horario


def _decimal_or_zero(value: Optional[object], quant: str) -> Decimal:
    target = Decimal(quant)
    if value is None:
        return Decimal("0").quantize(target)
    try:
        return Decimal(str(value)).quantize(target)
    except Exception:
        return Decimal("0").quantize(target)


def _epoch_to_datetime(epoch: Optional[int]) -> Optional[datetime]:
    if epoch in (None, 0):
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except Exception:
        return None


class MotorTrading:
    """
    Motor principal que gestiona la creación de señales, ejecución de operaciones
    y evaluación de resultados.
    """

    def __init__(self) -> None:
        self.gestor_core = GestorBotCore()
        self.channel_layer = get_channel_layer()

    def generar_senal(self, activo: str) -> Optional[Dict[str, Decimal | str]]:
        try:
            respuesta = obtener_ticks_history_sync(activo, count=2)
        except Exception as exc:
            self._enviar_evento(
                {"tipo": "error", "mensaje": f"No se pudieron obtener ticks: {exc}"}
            )
            return None

        if respuesta.get("error"):
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": f"Error desde Deriv al solicitar ticks: {respuesta['error'].get('message', 'desconocido')}",
                }
            )
            return None

        history = respuesta.get("history", {})
        precios = history.get("prices") or []
        if len(precios) < 2:
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": "Sin datos suficientes de ticks para generar señal.",
                }
            )
            return None

        anterior = Decimal(str(precios[-2]))
        actual = Decimal(str(precios[-1]))

        if actual == anterior:
            self._enviar_evento(
                {
                    "tipo": "info",
                    "mensaje": "Sin variación de precio en los últimos ticks.",
                }
            )
            return None

        direccion_original = (
            Operacion.Direccion.CALL if actual > anterior else Operacion.Direccion.PUT
        )
        direccion = direccion_original
        
        # MODO INVERSO: Si está activado, invertir la dirección
        config = self.gestor_core.configuracion
        if config.modo_inverso:
            direccion = Operacion.Direccion.PUT if direccion == Operacion.Direccion.CALL else Operacion.Direccion.CALL
            import sys
            from django.utils import timezone
            print(f"[{timezone.now():%Y-%m-%d %H:%M:%S}] 🔄 Modo inverso: {direccion_original} → {direccion} (Activo: {activo})", file=sys.stderr)
        
        contract_type = "CALL" if direccion == Operacion.Direccion.CALL else "PUT"
        variacion = (abs(actual - anterior) / anterior * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        confianza = min(variacion, Decimal("99.99"))

        return {
            "direccion": direccion,
            "contract_type": contract_type,
            "confianza": confianza,
            "duracion": 60,
            "unidad_duracion": "s",
            "variacion": variacion,
        }

    def _enviar_evento(self, data: Dict) -> None:
        if not self.channel_layer:
            return
        async_to_sync(self.channel_layer.group_send)(
            "deriv_estado",
            {"type": "recibir_evento_deriv", "data": data},
        )

    def _emitir_evento_operacion(self, operacion: Operacion) -> None:
        data = {
            "tipo": "operacion",
            "actualizar_panel": True,
            "operacion": {
                "numero_contrato": operacion.numero_contrato,
                "activo": operacion.activo,
                "direccion": operacion.direccion,
                "resultado": operacion.resultado,
                "beneficio": str(operacion.beneficio),
                "es_simulada": operacion.es_simulada,
                "hora_inicio": operacion.hora_inicio.isoformat()
                if operacion.hora_inicio
                else None,
                "hora_fin": operacion.hora_fin.isoformat()
                if operacion.hora_fin
                else None,
            },
        }
        self._enviar_evento(data)

    @transaction.atomic
    def ejecutar_ciclo(self) -> Optional[Operacion]:
        config = self.gestor_core.configuracion
        if config.estado != config.Estado.OPERANDO or config.en_operacion:
            return None

        self.gestor_core.sincronizar_balance_desde_api()
        config.refresh_from_db()
        if config.stop_loss_actual <= 0:
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": "Stop loss no configurado correctamente. No se puede operar.",
                }
            )
            return None

        activos_qs = ActivoPermitido.objects.filter(habilitado=True).order_by(
            "-winrate_simulacion", "nombre"
        )
        activos = priorizar_activos_por_horario(list(activos_qs))
        if not activos:
            self._enviar_evento(
                {"tipo": "error", "mensaje": "No hay activos habilitados para operar."}
            )
            return None

        mejor_activo: Optional[ActivoPermitido] = None
        mejor_senal: Optional[Dict[str, Decimal | str]] = None
        for activo in activos:
            senal_actual = self.generar_senal(activo.nombre)
            if not senal_actual:
                continue
            if mejor_senal is None or senal_actual["variacion"] > mejor_senal["variacion"]:
                mejor_activo = activo
                mejor_senal = senal_actual

        if not mejor_activo or not mejor_senal:
            self._enviar_evento(
                {
                    "tipo": "info",
                    "mensaje": "No se encontraron señales válidas entre los activos disponibles.",
                }
            )
            self.gestor_core.finalizar_operacion()
            return None

        self.gestor_core.marcar_operacion_en_curso(mejor_activo.nombre)
        monto_trade = self.gestor_core.obtener_monto_trade()
        senal = mejor_senal

        if not settings.DERIV_API_TOKEN or not settings.DERIV_APP_ID:
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": "Token o APP ID de Deriv no configurados. No se envió la operación.",
                }
            )
            self.gestor_core.finalizar_operacion()
            return None

        if not settings.DERIV_API_TOKEN:
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": "Token de Deriv no disponible para ejecutar la operación.",
                }
            )
            self.gestor_core.finalizar_operacion()
            return None

        try:
            respuesta = operar_contrato_sync(
                symbol=mejor_activo.nombre,
                amount=float(monto_trade),
                duration=senal["duracion"],
                duration_unit=senal["unidad_duracion"],
                contract_type=senal["contract_type"],
            )
        except Exception as exc:
            self._enviar_evento({"tipo": "error", "mensaje": str(exc)})
            self.gestor_core.finalizar_operacion()
            return None

        if respuesta.get("error"):
            error_info = respuesta.get("error", {})
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": f"Error de Deriv API: {error_info.get('message', 'Error desconocido')}",
                }
            )
            self.gestor_core.finalizar_operacion()
            return None

        open_contract = respuesta.get("proposal_open_contract", {})
        if not open_contract:
            self._enviar_evento(
                {
                    "tipo": "error",
                    "mensaje": "Respuesta inválida de Deriv: sin proposal_open_contract.",
                }
            )
            self.gestor_core.finalizar_operacion()
            return None

        contract_id_real = open_contract.get("contract_id") or respuesta.get("buy", {}).get(
            "contract_id"
        )
        if not contract_id_real:
            self._enviar_evento(
                {"tipo": "error", "mensaje": f"No se recibió contract_id de Deriv. Respuesta: {respuesta}"}
            )
            self.gestor_core.finalizar_operacion()
            return None

        beneficio = _decimal_or_zero(open_contract.get("profit", 0), "0.01")
        precio_entrada = _decimal_or_zero(
            open_contract.get("entry_spot") or open_contract.get("entry_tick") or open_contract.get("barrier"),
            "0.00001",
        )
        precio_cierre = _decimal_or_zero(
            open_contract.get("sell_spot")
            or open_contract.get("exit_tick")
            or open_contract.get("sell_price")
            or open_contract.get("current_spot"),
            "0.00001",
        )

        hora_inicio = _epoch_to_datetime(open_contract.get("date_start")) or timezone.now()
        hora_fin = _epoch_to_datetime(open_contract.get("date_expiry") or open_contract.get("sell_time")) or timezone.now()

        if beneficio > 0:
            resultado = Operacion.Resultado.GANADA
        elif beneficio < 0:
            resultado = Operacion.Resultado.PERDIDA
        else:
            resultado = Operacion.Resultado.PERDIDA

        operacion = Operacion.objetos.create(
            activo=mejor_activo.nombre,
            direccion=senal["direccion"],
            precio_entrada=precio_entrada,
            precio_cierre=precio_cierre,
            monto_invertido=monto_trade,
            confianza=senal["confianza"],
            resultado=resultado,
            numero_contrato=str(contract_id_real),
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            beneficio=beneficio,
            es_simulada=False,
        )

        self.gestor_core.registrar_resultado_operacion(operacion)
        self.gestor_core.finalizar_operacion()

        self._emitir_evento_operacion(operacion)
        return operacion

