"""
Servicios para el bot de trading inverso.
Este bot ejecuta la estrategia opuesta al bot principal usando EMAs.
"""
from decimal import Decimal
from typing import Optional, Dict, List
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from historial.models import Operacion as OperacionPrincipal
from integracion_deriv.client import operar_contrato_sync
from trading.services import _decimal_or_zero, _epoch_to_datetime
from trading.services_profesional import calcular_ema
from trading.models import IndicadoresActivo
from trading.risk import (
    calcular_monto_adaptativo,
    verificar_cooldown,
)
from core.models import ActivoPermitido

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
            
            # IMPORTANTE: balance_stop_loss_base solo se actualiza cuando el bot inverso gana
            # (en registrar_ganancia), NO cuando sincroniza desde Deriv
            # Esto asegura que el stop loss se base en el balance inicial del bot inverso
            
            # LÓGICA CRÍTICA: Stop loss basado en balance base del bot inverso, NO en balance compartido
            # El balance_stop_loss_base solo se actualiza cuando el bot inverso gana (en registrar_ganancia)
            # Esto evita que el stop loss se afecte por ganancias del bot principal
            
            # Si es la primera vez, inicializar balance_stop_loss_base
            if self.configuracion.balance_stop_loss_base <= 0:
                self.configuracion.balance_stop_loss_base = balance
            
            # Calcular stop loss basado en balance_stop_loss_base (balance inicial del bot inverso)
            # NO usar balance compartido de Deriv directamente
            balance_base = self.configuracion.balance_stop_loss_base
            nuevo_stop_loss = self.configuracion.calcular_stop_loss(balance_base)
            
            # CORRECCIÓN CRÍTICA: Recalcular stop loss si:
            # 1. El stop loss actual es mayor que el balance base (inconsistencia)
            # 2. El stop loss actual no coincide con el cálculo correcto (porcentaje cambió)
            stop_loss_esperado = nuevo_stop_loss
            diferencia = abs(self.configuracion.stop_loss_actual - stop_loss_esperado)
            
            # Si hay diferencia significativa (> $0.10) o el stop loss es mayor que el balance base, recalcular
            if self.configuracion.stop_loss_actual > balance_base or diferencia > Decimal("0.10"):
                self.configuracion.stop_loss_actual = stop_loss_esperado
            
            # Verificar si el balance actual (compartido) alcanzó el stop loss
            # El stop loss se calcula sobre balance_base, pero se verifica contra balance (compartido)
            if balance <= self.configuracion.stop_loss_actual:
                # El balance compartido alcanzó el stop loss del bot inverso
                # Esto puede pasar si el bot principal perdió mucho
                # En este caso, pausar el bot inverso
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
    Usa la misma estrategia de EMAs que el bot principal pero con dirección invertida.
    """
    
    def __init__(self):
        self.gestor = GestorBotInverso()
        self.channel_layer = get_channel_layer()
        self.ultimo_mensaje_diagnostico = None
        
        # Configuración SIMPLE - Estrategia basada en EMAs (igual que bot principal)
        self.duracion_trade_segundos = 60
        self.periodo_analisis_segundos = 120  # Analizar últimos 2 minutos
        self.ema_rapida_periodo = 10  # EMA rápida: 10 ticks
        self.ema_lenta_periodo = 30   # EMA lenta: 30 ticks
        self.umbral_separacion_pct = Decimal("0.01")  # Mínimo 0.01% de separación
    
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
    
    def _calcular_indicadores_activo(
        self, activo: ActivoPermitido
    ) -> Optional[Dict]:
        """
        Calcula indicadores SIMPLES basados en medias móviles (EMA).
        MISMA lógica que el bot principal, pero la dirección se invierte después.
        
        Returns:
            Diccionario con indicadores o None si no hay datos suficientes
        """
        from historial.models import Tick
        
        # Obtener ticks de los últimos 2 minutos
        desde = timezone.now() - timedelta(seconds=self.periodo_analisis_segundos)
        
        ticks = (
            Tick.objects.filter(
                activo=activo.nombre,
                epoch__gte=desde
            )
            .order_by("epoch")
        )
        
        if not ticks.exists():
            return None
        
        # Convertir a lista de precios
        precios = [Decimal(str(tick.precio)) for tick in ticks]
        
        # Necesitamos al menos 30 ticks para calcular EMA lenta
        if len(precios) < self.ema_lenta_periodo:
            return None
        
        precio_actual = precios[-1]
        
        # Calcular EMAs (igual que bot principal)
        ema_rapida = calcular_ema(precios, self.ema_rapida_periodo)
        ema_lenta = calcular_ema(precios, self.ema_lenta_periodo)
        
        if ema_rapida == Decimal("0") or ema_lenta == Decimal("0"):
            return None
        
        # Determinar dirección basada en crossover de EMAs
        # NOTA: Esta es la dirección que usaría el bot principal
        if ema_rapida > ema_lenta:
            direccion_principal = "CALL"  # Bot principal haría CALL
            separacion_pct = ((ema_rapida - ema_lenta) / ema_lenta * 100) if ema_lenta > 0 else Decimal("0")
        elif ema_rapida < ema_lenta:
            direccion_principal = "PUT"  # Bot principal haría PUT
            separacion_pct = ((ema_lenta - ema_rapida) / ema_rapida * 100) if ema_rapida > 0 else Decimal("0")
        else:
            direccion_principal = "NONE"
            separacion_pct = Decimal("0")
        
        # INVERTIR la dirección para el bot inverso
        direccion = self._invertir_direccion(direccion_principal)
        
        # Calcular volatilidad simple
        precio_max = max(precios)
        precio_min = min(precios)
        volatilidad = ((precio_max - precio_min) / precio_min * 100) if precio_min > 0 else Decimal("0")
        
        return {
            "ema_rapida": ema_rapida,
            "ema_lenta": ema_lenta,
            "precio_actual": precio_actual,
            "direccion_sugerida": direccion,  # Ya invertida
            "separacion_pct": separacion_pct,
            "volatilidad": volatilidad,
            "ticks_analizados": len(precios),
        }
    
    def _evaluar_activos(self) -> List[Dict]:
        """
        Evalúa activos con estrategia SIMPLE basada en EMAs (dirección invertida).
        MISMA lógica que bot principal pero con dirección opuesta.
        
        Returns:
            Lista de activos con sus indicadores y scores, ordenados por separación de EMAs
        """
        # Obtener activos habilitados
        activos = list(ActivoPermitido.objects.filter(habilitado=True))
        resultados = []
        
        for activo in activos:
            # Solo verificar cooldown básico
            if not verificar_cooldown(activo.id):
                continue
            
            # Calcular indicadores (EMAs con dirección invertida)
            indicadores_data = self._calcular_indicadores_activo(activo)
            if not indicadores_data:
                continue
            
            # Validar que hay suficiente separación entre EMAs
            if indicadores_data["separacion_pct"] < self.umbral_separacion_pct:
                continue
            
            # Validar que la dirección es clara
            if indicadores_data["direccion_sugerida"] == "NONE":
                continue
            
            # Guardar indicadores
            indicadores, _ = IndicadoresActivo.objects.update_or_create(
                activo=activo,
                defaults={
                    "momentum_simple": indicadores_data["ema_rapida"] - indicadores_data["ema_lenta"],
                    "momentum_pct": indicadores_data["separacion_pct"],
                    "volatilidad": indicadores_data["volatilidad"],
                    "precio_actual": indicadores_data["precio_actual"],
                    "direccion_sugerida": indicadores_data["direccion_sugerida"],
                    "ticks_analizados": indicadores_data["ticks_analizados"],
                    "score_total": indicadores_data["separacion_pct"],
                },
            )
            
            resultados.append({
                "activo": activo,
                "indicadores": indicadores,
                "score": indicadores_data["separacion_pct"],
            })
        
        # Ordenar por separación descendente
        resultados.sort(key=lambda x: x["score"], reverse=True)
        
        return resultados
    
    @transaction.atomic
    def ejecutar_ciclo_ema(self) -> Optional[OperacionInversa]:
        """
        Ejecuta un ciclo completo usando estrategia EMA (dirección invertida).
        MISMA lógica que bot principal pero con dirección opuesta.
        
        Returns:
            Operación inversa ejecutada o None
        """
        config = self.gestor.configuracion
        
        # Verificaciones previas
        if config.estado != config.Estado.OPERANDO or config.en_operacion:
            return None
        
        self.gestor.sincronizar_balance_desde_api()
        config.refresh_from_db()
        
        if config.stop_loss_actual <= 0:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": "Stop loss no está configurado correctamente.",
            })
            return None
        
        # Evaluar todos los activos con EMAs (dirección invertida)
        self._enviar_evento({
            "tipo": "info",
            "mensaje": "Evaluando activos con estrategia EMA (inversa)...",
        })
        
        resultados = self._evaluar_activos()
        
        if not resultados:
            activos_habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
            from trading.models import CooldownActivo
            cooldowns_activos = CooldownActivo.objects.filter(finaliza_en__gt=timezone.now()).count()
            
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"No se encontraron señales EMA válidas (inversas). Habilitados: {activos_habilitados}, En cooldown: {cooldowns_activos}",
            })
            return None
        
        # Seleccionar el mejor activo (mayor separación entre EMAs)
        mejor_resultado = resultados[0]
        mejor_activo = mejor_resultado["activo"]
        mejor_indicadores = mejor_resultado["indicadores"]
        mejor_score = mejor_resultado["score"]
        
        # Validar que la separación es suficiente
        if mejor_score < self.umbral_separacion_pct:
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"Separación EMA insuficiente ({mejor_score:.4f}%) en {mejor_activo.nombre}. Mínimo requerido: {self.umbral_separacion_pct}%",
            })
            return None
        
        # Determinar dirección (ya está invertida en _calcular_indicadores_activo)
        direccion = mejor_indicadores.direccion_sugerida
        
        if direccion == "NONE":
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"Sin señal EMA clara en {mejor_activo.nombre}. Esperando siguiente ciclo.",
            })
            return None
        
        contract_type = direccion
        
        # Calcular monto adaptativo
        monto_trade = calcular_monto_adaptativo(
            balance=config.balance_actual,
            volatilidad=mejor_indicadores.volatilidad,
        )
        
        # Marcar operación en curso
        config.en_operacion = True
        config.activo_seleccionado = mejor_activo.nombre
        config.save(update_fields=["en_operacion", "activo_seleccionado", "ultima_actualizacion"])
        
        # Ejecutar contrato
        if not settings.DERIV_API_TOKEN:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": "Token de Deriv no configurado.",
            })
            config.en_operacion = False
            config.save(update_fields=["en_operacion", "ultima_actualizacion"])
            return None
        
        try:
            respuesta = operar_contrato_sync(
                symbol=mejor_activo.nombre,
                amount=float(monto_trade),
                duration=60,
                duration_unit="s",
                contract_type=contract_type,
            )
        except Exception as exc:
            self._enviar_evento({"tipo": "error", "mensaje": str(exc)})
            config.en_operacion = False
            config.save(update_fields=["en_operacion", "ultima_actualizacion"])
            return None
        
        if respuesta.get("error"):
            error_info = respuesta.get("error", {})
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"Error de Deriv API: {error_info.get('message', 'Error desconocido')}",
            })
            config.en_operacion = False
            config.save(update_fields=["en_operacion", "ultima_actualizacion"])
            return None
        
        open_contract = respuesta.get("proposal_open_contract", {})
        if not open_contract:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": "Respuesta inválida de Deriv: sin proposal_open_contract.",
            })
            config.en_operacion = False
            config.save(update_fields=["en_operacion", "ultima_actualizacion"])
            return None
        
        # CRÍTICO: Validar contract_id ANTES de crear la operación (evitar PEND-)
        contract_id_real = open_contract.get("contract_id") or respuesta.get("buy", {}).get("contract_id")
        if not contract_id_real:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"No se recibió contract_id de Deriv. NO se creará operación. Respuesta: {respuesta}",
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
        
        beneficio = _decimal_or_zero(open_contract.get("profit", 0), "0.01")
        precio_entrada = _decimal_or_zero(
            open_contract.get("entry_spot") or open_contract.get("entry_tick") or mejor_indicadores.precio_actual,
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
            resultado = OperacionInversa.Resultado.GANADA
        elif beneficio < 0:
            resultado = OperacionInversa.Resultado.PERDIDA
        else:
            resultado = OperacionInversa.Resultado.PERDIDA
        
        # Crear operación inversa SOLO si tenemos contract_id válido
        operacion_inversa = OperacionInversa.objects.create(
            activo=mejor_activo.nombre,
            direccion=OperacionInversa.Direccion.CALL if direccion == "CALL" else OperacionInversa.Direccion.PUT,
            precio_entrada=precio_entrada,
            precio_cierre=precio_cierre,
            monto_invertido=monto_trade,
            confianza=mejor_score,
            resultado=resultado,
            numero_contrato=str(contract_id_real),  # SIEMPRE numérico, nunca PEND-
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            beneficio=beneficio,
            es_simulada=False,
        )
        
        # Actualizar balance y estadísticas
        if beneficio > 0:
            config.registrar_ganancia(beneficio)
            self._enviar_evento({
                "tipo": "success",
                "mensaje": f"✅ Operación INVERSA GANADA: {mejor_activo.nombre} {direccion} | Beneficio: ${beneficio}",
            })
        else:
            config.registrar_perdida(abs(beneficio))
            self._enviar_evento({
                "tipo": "warning",
                "mensaje": f"❌ Operación INVERSA PERDIDA: {mejor_activo.nombre} {direccion} | Pérdida: ${abs(beneficio)}",
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
        
        # Ejecutar operación en Deriv usando la misma función que el bot principal
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
            
            # Obtener datos del contrato de la respuesta (igual que el bot principal)
            open_contract = resultado_deriv.get("proposal_open_contract", {})
            if not open_contract:
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": "Respuesta inválida de Deriv: sin proposal_open_contract.",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            contract_id_real = open_contract.get("contract_id") or resultado_deriv.get("buy", {}).get("contract_id")
            if not contract_id_real:
                self._enviar_evento({
                    "tipo": "error",
                    "mensaje": f"No se recibió contract_id de Deriv. Respuesta: {resultado_deriv}",
                })
                config.en_operacion = False
                config.save(update_fields=["en_operacion", "ultima_actualizacion"])
                return None
            
            # Calcular beneficio (igual que el bot principal)
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
            
            # Crear operación inversa
            operacion_inversa = OperacionInversa.objects.create(
                activo=operacion_principal.activo,
                direccion=OperacionInversa.Direccion.CALL if direccion_inversa == "CALL" else OperacionInversa.Direccion.PUT,
                precio_entrada=precio_entrada,
                precio_cierre=precio_cierre,
                monto_invertido=monto_trade,
                confianza=Decimal("100.00"),  # 100% porque es inverso del principal
                resultado=resultado,
                numero_contrato=str(contract_id_real),  # Usar contract_id_real
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

