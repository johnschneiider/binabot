"""
Servicios para el bot de trading inverso.
Este bot ejecuta la estrategia opuesta al bot principal.
"""
from decimal import Decimal
from typing import Optional
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from historial.models import Operacion as OperacionPrincipal
from integracion_deriv.client import operar_contrato_sync
from trading.services import _decimal_or_zero, _epoch_to_datetime
from trading.services_profesional import MotorTradingProfesional

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
            # La respuesta de Deriv tiene estructura: {"balance": {"balance": 85.67, "currency": "USD", ...}}
            balance_info = respuesta.get("balance")
            if not balance_info:
                return
            balance = Decimal(str(balance_info.get("balance", "0")))
            
            # SIEMPRE actualizar el balance desde Deriv, incluso si es 0
            # Esto asegura que siempre mostremos el balance real de la cuenta
            balance_anterior = self.configuracion.balance_actual
            self.configuracion.balance_actual = balance
            
            # Si el balance cambió o es la primera vez, inicializar bases
            if balance_anterior <= 0 and balance > 0:
                # Primera inicialización: establecer bases
                if self.configuracion.balance_meta_base <= 0:
                    self.configuracion.balance_meta_base = balance
                if self.configuracion.balance_stop_loss_base <= 0:
                    self.configuracion.balance_stop_loss_base = balance
                if self.configuracion.stop_loss_actual <= 0:
                    self.configuracion.stop_loss_actual = self.configuracion.calcular_stop_loss(balance)
            
            # Lógica de stop loss:
            # 1. CORRECCIÓN CRÍTICA: Si el stop loss actual es mayor que el balance, recalcular
            #    Esto puede pasar si el balance bajó desde una inicialización previa
            # 2. Si el balance sube, aplicar trailing stop loss (solo sube)
            # 3. Si el balance baja, el stop loss NO baja (se mantiene fijo como protección)
            
            nuevo_stop_loss = self.configuracion.calcular_stop_loss(balance)
            
            # CORRECCIÓN CRÍTICA: Si el stop loss actual es mayor que el balance, SIEMPRE recalcular
            # Esto debe ejecutarse independientemente del estado del bot
            if self.configuracion.stop_loss_actual > balance:
                self.configuracion.stop_loss_actual = nuevo_stop_loss
                self.configuracion.balance_stop_loss_base = balance
            # Solo aplicar trailing stop loss si está operando
            elif self.configuracion.estado == ConfiguracionBotInverso.Estado.OPERANDO:
                # Trailing stop loss: solo sube, nunca baja
                if nuevo_stop_loss > self.configuracion.stop_loss_actual:
                    self.configuracion.stop_loss_actual = nuevo_stop_loss
                    self.configuracion.balance_stop_loss_base = balance
                # Si el balance baja, el stop_loss_actual NO cambia (se mantiene fijo)
            
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
    Monitorea las operaciones del bot principal y ejecuta la dirección opuesta.
    """
    
    def __init__(self):
        self.gestor = GestorBotInverso()
        self.channel_layer = get_channel_layer()
        self.motor_principal = MotorTradingProfesional()  # Para reutilizar lógica de análisis
    
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
        
        # Invertir la dirección del bot principal
        direccion_inversa = self._invertir_direccion(operacion_principal.direccion)
        
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
            "mensaje": f"🔄 Ejecutando operación INVERSA: {operacion_principal.activo} {direccion_inversa} (Principal: {operacion_principal.direccion})",
        })
        
        # Ejecutar operación en Deriv
        try:
            resultado_deriv = operar_contrato_sync(
                symbol=operacion_principal.activo,
                direction=direccion_inversa,
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
            buy = resultado_deriv.get("buy")
            if not buy or not buy.get("contract_id"):
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": "Deriv no retornó contract_id. No se creará operación.",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            contract_id = buy.get("contract_id")
            
            # Esperar resultado del contrato
            import time
            tiempo_espera = 0
            tiempo_maximo = 70  # 60 segundos + margen
            
            while tiempo_espera < tiempo_maximo:
                time.sleep(2)
                tiempo_espera += 2
                
                # Verificar estado del contrato
                from integracion_deriv.client import DerivWebsocketClient
                import asyncio
                
                client = DerivWebsocketClient()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                contract_info = loop.run_until_complete(client.obtener_contrato(contract_id))
                loop.close()
                
                if contract_info and contract_info.get("status") == "sold":
                    break
            
            # Obtener información final del contrato
            client = DerivWebsocketClient()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            open_contract = loop.run_until_complete(client.obtener_contrato(contract_id))
            loop.close()
            
            if not open_contract:
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": "No se pudo obtener información del contrato final.",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            # Calcular beneficio
            beneficio = _decimal_or_zero(
                open_contract.get("profit") or open_contract.get("sell_price"),
                "0.00"
            )
            
            precio_entrada = _decimal_or_zero(
                open_contract.get("buy_price") or open_contract.get("entry_spot"),
                "0.00001"
            )
            precio_cierre = _decimal_or_zero(
                open_contract.get("sell_price") or open_contract.get("exit_spot") or open_contract.get("current_spot"),
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
            
            # Crear operación inversa
            operacion_inversa = OperacionInversa.objects.create(
                activo=operacion_principal.activo,
                direccion=OperacionInversa.Direccion.CALL if direccion_inversa == "CALL" else OperacionInversa.Direccion.PUT,
                precio_entrada=precio_entrada,
                precio_cierre=precio_cierre,
                monto_invertido=monto_trade,
                confianza=Decimal("100.00"),  # 100% porque es inverso del principal
                resultado=resultado,
                numero_contrato=contract_id,
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
                    "mensaje": f"⚠️ Stop loss alcanzado. Pausando bot inverso por 24 horas.",
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

