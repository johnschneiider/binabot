"""
Servicios para el bot de trading inverso.
Este bot reacciona a las operaciones del bot principal ejecutando la dirección opuesta.
NO evalúa activos por sí mismo - solo reacciona al bot principal.
"""
from decimal import Decimal
from typing import Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from historial.models import Operacion as OperacionPrincipal
from integracion_deriv.client import operar_contrato_sync
from trading.services import _decimal_or_zero, _epoch_to_datetime

from .models import OperacionInversa, ConfiguracionBotInverso


class GestorBotInverso:
    """Gestor del bot inverso, similar a GestorBotCore pero independiente."""
    
    def __init__(self):
        self.configuracion = ConfiguracionBotInverso.obtener()
    
    def sincronizar_balance_desde_api(self) -> None:
        """Sincroniza el balance desde la API de Deriv. SIEMPRE actualiza desde Deriv."""
        from integracion_deriv.client import obtener_balance_sync
        
        try:
            respuesta = obtener_balance_sync()
            balance_info = respuesta.get("balance")
            if not balance_info:
                return
            balance = Decimal(str(balance_info.get("balance", "0")))
            
            balance_anterior = self.configuracion.balance_actual
            self.configuracion.balance_actual = balance
            
            # Si el balance cambió o es la primera vez, inicializar bases
            if balance_anterior <= 0 and balance > 0:
                if self.configuracion.balance_meta_base <= 0:
                    self.configuracion.balance_meta_base = balance
                if self.configuracion.balance_stop_loss_base <= 0:
                    self.configuracion.balance_stop_loss_base = balance
                if self.configuracion.stop_loss_actual <= 0:
                    self.configuracion.stop_loss_actual = self.configuracion.calcular_stop_loss(balance)
            
            # Si es la primera vez, inicializar balance_stop_loss_base
            if self.configuracion.balance_stop_loss_base <= 0:
                self.configuracion.balance_stop_loss_base = balance
            
            # Calcular stop loss basado en balance_stop_loss_base
            balance_base = self.configuracion.balance_stop_loss_base
            nuevo_stop_loss = self.configuracion.calcular_stop_loss(balance_base)
            
            # Recalcular stop loss si hay inconsistencia
            stop_loss_esperado = nuevo_stop_loss
            diferencia = abs(self.configuracion.stop_loss_actual - stop_loss_esperado)
            
            if self.configuracion.stop_loss_actual > balance_base or diferencia > Decimal("0.10"):
                self.configuracion.stop_loss_actual = stop_loss_esperado
            
            # Verificar si el balance actual alcanzó el stop loss
            if balance <= self.configuracion.stop_loss_actual:
                if self.configuracion.estado == ConfiguracionBotInverso.Estado.OPERANDO:
                    self.configuracion.pausar(horas=1)
            
            self.configuracion.save(update_fields=["balance_actual", "stop_loss_actual", "balance_stop_loss_base", "balance_meta_base", "ultima_actualizacion"])
        except Exception as e:
            print(f"Error sincronizando balance inverso: {e}")
    
    def obtener_estado(self):
        """Obtiene el estado actual del bot inverso."""
        return self.configuracion
    
    def finalizar_operacion(self) -> None:
        """Marca que el bot ya no está en operación."""
        self.configuracion.en_operacion = False
        self.configuracion.save(update_fields=["en_operacion", "ultima_actualizacion"])


class MotorTradingInverso:
    """
    Motor de trading inverso.
    Reacciona a las operaciones del bot principal ejecutando la dirección opuesta.
    NO evalúa activos por sí mismo - solo reacciona.
    """
    
    def __init__(self):
        self.gestor = GestorBotInverso()
        self.channel_layer = get_channel_layer()
    
    def _enviar_evento(self, data: dict) -> None:
        """Envía evento a través de WebSockets."""
        if not self.channel_layer:
            return
        try:
            async_to_sync(self.channel_layer.group_send)(
                "deriv_estado_inverso",
                {"type": "recibir_evento_deriv_inverso", "data": data},
            )
        except Exception as e:
            print(f"Error enviando evento WebSocket del bot inverso: {e}")
    
    def _invertir_direccion(self, direccion: str) -> str:
        """Invierte la dirección: CALL -> PUT, PUT -> CALL."""
        if direccion == "CALL":
            return "PUT"
        elif direccion == "PUT":
            return "CALL"
        return direccion
    
    @transaction.atomic
    def ejecutar_ciclo_inverso(self, operacion_principal: OperacionPrincipal) -> Optional[OperacionInversa]:
        """
        Ejecuta una operación inversa basada en la operación del bot principal.
        El bot principal ya decidió la operación usando EMAs, aquí solo invertimos la dirección.
        
        Args:
            operacion_principal: Operación del bot principal que se acaba de ejecutar
        
        Returns:
            Operación inversa ejecutada o None
        """
        config = self.gestor.configuracion
        
        # Verificaciones previas
        if config.estado != config.Estado.OPERANDO or config.en_operacion:
            return None
        
        # Verificar stop loss
        if config.balance_actual <= config.stop_loss_actual:
            self._enviar_evento({
                "tipo": "warning",
                "mensaje": f"Balance ({config.balance_actual}) alcanzó stop loss ({config.stop_loss_actual}). Pausando bot inverso.",
            })
            config.pausar(horas=1)
            return None
        
        # INVERTIR la dirección del bot principal
        direccion_principal = operacion_principal.direccion
        direccion_inversa = self._invertir_direccion(
            "CALL" if direccion_principal == OperacionPrincipal.Direccion.CALL else "PUT"
        )
        
        # Calcular monto del trade
        monto_trade = config.calcular_monto_trade()
        
        # Verificar que hay balance suficiente
        if config.balance_actual < monto_trade:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"Balance insuficiente para operar. Balance: {config.balance_actual}, Requerido: {monto_trade}",
            })
            return None
        
        # Marcar que está en operación
        config.en_operacion = True
        config.activo_seleccionado = operacion_principal.activo
        config.save(update_fields=["en_operacion", "activo_seleccionado", "ultima_actualizacion"])
        
        self._enviar_evento({
            "tipo": "info",
            "mensaje": f"🔄 Ejecutando operación INVERSA: {operacion_principal.activo} {direccion_inversa} (Principal: {direccion_principal})",
        })
        
        # Ejecutar operación en Deriv
        try:
            resultado_deriv = operar_contrato_sync(
                symbol=operacion_principal.activo,
                contract_type=direccion_inversa,
                amount=float(monto_trade),
                duration=60,
                duration_unit="s",
            )
            
            if not resultado_deriv or resultado_deriv.get("error"):
                error_msg = resultado_deriv.get("error", {}).get("message", "Error desconocido") if resultado_deriv else "Sin respuesta de Deriv"
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": f"Error al operar en Deriv: {error_msg}",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            # Obtener datos del contrato
            open_contract = resultado_deriv.get("proposal_open_contract", {})
            if not open_contract:
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": "Respuesta inválida de Deriv: sin proposal_open_contract.",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            # CRÍTICO: Validar contract_id ANTES de crear la operación (evitar PEND-)
            contract_id_real = open_contract.get("contract_id") or resultado_deriv.get("buy", {}).get("contract_id")
            if not contract_id_real:
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": f"No se recibió contract_id de Deriv. NO se creará operación. Respuesta: {resultado_deriv}",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            # Validar que contract_id es numérico (no PEND-)
            try:
                int(contract_id_real)
            except (ValueError, TypeError):
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": f"Contract ID inválido (no numérico): {contract_id_real}. NO se creará operación.",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            # Calcular beneficio
            beneficio = _decimal_or_zero(open_contract.get("profit", 0), "0.01")
            precio_entrada = _decimal_or_zero(
                open_contract.get("entry_spot") or open_contract.get("entry_tick") or open_contract.get("current_spot"),
                "0.00001"
            )
            precio_cierre = _decimal_or_zero(
                open_contract.get("exit_spot") or open_contract.get("current_spot") or precio_entrada,
                "0.00001"
            )
            hora_inicio = _epoch_to_datetime(open_contract.get("date_start")) or timezone.now()
            hora_fin = _epoch_to_datetime(open_contract.get("date_expiry") or open_contract.get("sell_time")) or timezone.now()
            
            if beneficio > 0:
                resultado = OperacionInversa.Resultado.GANADA
            elif beneficio < 0:
                resultado = OperacionInversa.Resultado.PERDIDA
            else:
                resultado = OperacionInversa.Resultado.PERDIDA
            
            # Crear operación inversa SOLO si tenemos contract_id válido
            operacion_inversa = OperacionInversa.objects.create(
                activo=operacion_principal.activo,
                direccion=OperacionInversa.Direccion.CALL if direccion_inversa == "CALL" else OperacionInversa.Direccion.PUT,
                precio_entrada=precio_entrada,
                precio_cierre=precio_cierre,
                monto_invertido=monto_trade,
                confianza=Decimal("100.00"),  # 100% porque es inverso del principal
                resultado=resultado,
                numero_contrato=str(contract_id_real),  # SIEMPRE numérico, nunca PEND-
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                beneficio=beneficio,
                es_simulada=False,
                operacion_principal_id=operacion_principal.numero_contrato,
            )
            
            # Actualizar balance y estadísticas
            if beneficio > 0:
                config.registrar_ganancia(beneficio)
                self._enviar_evento({
                    "tipo": "success",
                    "mensaje": f"✅ Operación INVERSA GANADA: {operacion_principal.activo} {direccion_inversa} | Beneficio: ${beneficio}",
                })
            else:
                config.registrar_perdida(abs(beneficio))
                self._enviar_evento({
                    "tipo": "warning",
                    "mensaje": f"❌ Operación INVERSA PERDIDA: {operacion_principal.activo} {direccion_inversa} | Pérdida: ${abs(beneficio)}",
                })
            
            # Verificar stop loss después de la pérdida
            if beneficio < 0 and config.balance_actual <= config.stop_loss_actual:
                self._enviar_evento({
                    "tipo": "warning",
                    "mensaje": f"⚠️ Stop loss alcanzado. Pausando bot inverso por 1 hora.",
                })
                config.pausar(horas=1)
            
            config.en_operacion = False
            config.save(update_fields=["en_operacion", "ultima_actualizacion"])
            
            # Sincronizar balance desde API
            self.gestor.sincronizar_balance_desde_api()
            
            return operacion_inversa
            
        except Exception as e:
            import traceback
            error_msg = f"Error ejecutando operación inversa: {str(e)}\n{traceback.format_exc()}"
            self._enviar_evento({
                "tipo": "error",
                "mensaje": error_msg,
            })
            config.en_operacion = False
            config.save(update_fields=["en_operacion", "ultima_actualizacion"])
            return None
