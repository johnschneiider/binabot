"""
Motor de trading profesional con estrategia SIMPLE basada en medias móviles (EMA).
Estrategia simplificada: EMA rápida vs EMA lenta para determinar dirección.
"""
from datetime import timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import ActivoPermitido
from core.services import GestorBotCore
from historial.models import Operacion
from integracion_deriv.client import operar_contrato_sync
from trading.services import _decimal_or_zero, _epoch_to_datetime
from trading.models import IndicadoresActivo
from trading.risk import (
    calcular_monto_adaptativo,
    verificar_cooldown,
)


def calcular_ema(precios: List[Decimal], periodo: int) -> Decimal:
    """
    Calcula la Media Móvil Exponencial (EMA) de una lista de precios.
    
    Args:
        precios: Lista de precios ordenados cronológicamente
        periodo: Período de la EMA (ej: 10, 20, 30)
    
    Returns:
        Valor de la EMA o Decimal("0") si no hay suficientes datos
    """
    if len(precios) < periodo:
        return Decimal("0")
    
    # Usar solo los últimos 'periodo' precios
    precios_periodo = precios[-periodo:]
    
    # Calcular EMA: empezar con SMA, luego aplicar fórmula exponencial
    sma = sum(precios_periodo) / Decimal(str(len(precios_periodo)))
    
    # Multiplicador para EMA
    multiplicador = Decimal("2") / Decimal(str(periodo + 1))
    
    # Calcular EMA iterativamente
    ema = sma
    for precio in precios_periodo:
        ema = (precio * multiplicador) + (ema * (Decimal("1") - multiplicador))
    
    return ema.quantize(Decimal("0.00001"))


class MotorTradingProfesional:
    """
    Motor de trading profesional con estrategia SIMPLE basada en medias móviles.
    Estrategia: EMA rápida (10) vs EMA lenta (30) - crossover determina dirección.
    """

    def __init__(self) -> None:
        self.gestor_core = GestorBotCore()
        self.channel_layer = get_channel_layer()
        self.ultimo_mensaje_diagnostico = None
        
        # Configuración SIMPLE - Estrategia basada en EMAs
        self.duracion_trade_segundos = 60
        self.periodo_analisis_segundos = 120  # Analizar últimos 2 minutos para tener suficientes ticks
        self.ema_rapida_periodo = 10  # EMA rápida: 10 ticks
        self.ema_lenta_periodo = 30   # EMA lenta: 30 ticks
        self.umbral_separacion_pct = Decimal("0.01")  # Mínimo 0.01% de separación entre EMAs para operar

    def _enviar_evento(self, data: Dict) -> None:
        """Envía evento a través de WebSockets."""
        if data.get("tipo") in ("info", "error", "warning"):
            self.ultimo_mensaje_diagnostico = data.get("mensaje", "")
        
        if not self.channel_layer:
            return
        async_to_sync(self.channel_layer.group_send)(
            "deriv_estado",
            {"type": "recibir_evento_deriv", "data": data},
        )

    def _calcular_indicadores_activo(
        self, activo: ActivoPermitido
    ) -> Optional[Dict]:
        """
        Calcula indicadores SIMPLES basados en medias móviles (EMA).
        
        Estrategia:
        - EMA rápida (10 períodos) vs EMA lenta (30 períodos)
        - Si EMA rápida > EMA lenta → CALL (tendencia alcista)
        - Si EMA rápida < EMA lenta → PUT (tendencia bajista)
        - Solo operar si hay suficiente separación entre EMAs (evitar ruido)
        
        Returns:
            Diccionario con indicadores o None si no hay datos suficientes
        """
        from historial.models import Tick
        
        # Obtener ticks de los últimos 2 minutos (necesitamos al menos 30 ticks para EMA lenta)
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
        
        # Calcular EMAs
        ema_rapida = calcular_ema(precios, self.ema_rapida_periodo)
        ema_lenta = calcular_ema(precios, self.ema_lenta_periodo)
        
        if ema_rapida == Decimal("0") or ema_lenta == Decimal("0"):
            return None
        
        # Determinar dirección basada en crossover de EMAs
        if ema_rapida > ema_lenta:
            direccion = "CALL"
            separacion_pct = ((ema_rapida - ema_lenta) / ema_lenta * 100) if ema_lenta > 0 else Decimal("0")
        elif ema_rapida < ema_lenta:
            direccion = "PUT"
            separacion_pct = ((ema_lenta - ema_rapida) / ema_rapida * 100) if ema_rapida > 0 else Decimal("0")
        else:
            direccion = "NONE"
            separacion_pct = Decimal("0")
        
        # Calcular volatilidad simple (rango de precios)
        precio_max = max(precios)
        precio_min = min(precios)
        volatilidad = ((precio_max - precio_min) / precio_min * 100) if precio_min > 0 else Decimal("0")
        
        return {
            "ema_rapida": ema_rapida,
            "ema_lenta": ema_lenta,
            "precio_actual": precio_actual,
            "direccion_sugerida": direccion,
            "separacion_pct": separacion_pct,
            "volatilidad": volatilidad,
            "ticks_analizados": len(precios),
        }

    def _evaluar_activos(self) -> List[Dict]:
        """
        Evalúa activos con estrategia SIMPLE basada en EMAs.
        Eliminada toda la complejidad: winrate histórico, horarios, etc.
        Solo EMAs puras.
        
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
            
            # Calcular indicadores (EMAs)
            indicadores_data = self._calcular_indicadores_activo(activo)
            if not indicadores_data:
                continue
            
            # Validar que hay suficiente separación entre EMAs (evitar ruido)
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
                    "score_total": indicadores_data["separacion_pct"],  # Score = separación de EMAs
                },
            )
            
            resultados.append({
                "activo": activo,
                "indicadores": indicadores,
                "score": indicadores_data["separacion_pct"],  # Mayor separación = mejor señal
            })
        
        # Ordenar por separación descendente (mayor separación = mejor señal)
        resultados.sort(key=lambda x: x["score"], reverse=True)
        
        return resultados

    @transaction.atomic
    def ejecutar_ciclo(self) -> Optional[Operacion]:
        """
        Ejecuta un ciclo completo de trading profesional.
        
        Returns:
            Operación ejecutada o None
        """
        config = self.gestor_core.configuracion
        
        # Verificaciones previas
        if config.estado != config.Estado.OPERANDO or config.en_operacion:
            return None
        
        self.gestor_core.sincronizar_balance_desde_api()
        config.refresh_from_db()
        
        if config.stop_loss_actual <= 0:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": "Stop loss no está configurado correctamente.",
            })
            return None
        
        # Evaluar todos los activos
        self._enviar_evento({
            "tipo": "info",
            "mensaje": "Evaluando activos con estrategia EMA...",
        })
        
        resultados = self._evaluar_activos()
        
        if not resultados:
            activos_habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
            from trading.models import CooldownActivo
            cooldowns_activos = CooldownActivo.objects.filter(finaliza_en__gt=timezone.now()).count()
            
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"No se encontraron señales EMA válidas. Habilitados: {activos_habilitados}, En cooldown: {cooldowns_activos}",
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
        
        # Determinar dirección basada en EMAs
        direccion = mejor_indicadores.direccion_sugerida
        
        if direccion == "NONE":
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"Sin señal EMA clara en {mejor_activo.nombre}. Esperando siguiente ciclo.",
            })
            return None
        
        # MODO INVERSO: Si está activado, invertir la dirección
        direccion_original = direccion
        if config.modo_inverso:
            direccion = "PUT" if direccion == "CALL" else "CALL"
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"🔄 Modo inverso: {direccion_original} → {direccion} (Activo: {mejor_activo.nombre})",
            })
            import sys
            print(f"[{timezone.now():%Y-%m-%d %H:%M:%S}] 🔄 Modo inverso: {direccion_original} → {direccion} (Activo: {mejor_activo.nombre})", file=sys.stderr)
        
        contract_type = direccion
        
        # Calcular monto adaptativo
        monto_trade = calcular_monto_adaptativo(
            balance=config.balance_actual,
            volatilidad=mejor_indicadores.volatilidad,
        )
        
        # Marcar operación en curso
        self.gestor_core.marcar_operacion_en_curso(mejor_activo.nombre)
        
        # Ejecutar contrato
        if not settings.DERIV_API_TOKEN:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": "Token de Deriv no configurado.",
            })
            self.gestor_core.finalizar_operacion()
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
            self.gestor_core.finalizar_operacion()
            return None
        
        if respuesta.get("error"):
            error_info = respuesta.get("error", {})
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"Error de Deriv API: {error_info.get('message', 'Error desconocido')}",
            })
            self.gestor_core.finalizar_operacion()
            return None
        
        open_contract = respuesta.get("proposal_open_contract", {})
        if not open_contract:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": "Respuesta inválida de Deriv: sin proposal_open_contract.",
            })
            self.gestor_core.finalizar_operacion()
            return None
        
        # CRÍTICO: Validar contract_id ANTES de crear la operación (evitar PEND-)
        contract_id_real = open_contract.get("contract_id") or respuesta.get("buy", {}).get("contract_id")
        if not contract_id_real:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"No se recibió contract_id de Deriv. NO se creará operación. Respuesta: {respuesta}",
            })
            self.gestor_core.finalizar_operacion()
            return None
        
        # Validar que contract_id es numérico (no PEND-)
        try:
            int(contract_id_real)
        except (ValueError, TypeError):
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"Contract ID inválido (no numérico): {contract_id_real}. NO se creará operación.",
            })
            self.gestor_core.finalizar_operacion()
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
            resultado = Operacion.Resultado.GANADA
        elif beneficio < 0:
            resultado = Operacion.Resultado.PERDIDA
        else:
            resultado = Operacion.Resultado.PERDIDA
        
        # Crear operación SOLO si tenemos contract_id válido
        operacion = Operacion.objetos.create(
            activo=mejor_activo.nombre,
            direccion=Operacion.Direccion.CALL if direccion == "CALL" else Operacion.Direccion.PUT,
            precio_entrada=precio_entrada,
            precio_cierre=precio_cierre,
            monto_invertido=monto_trade,
            confianza=mejor_score,  # Usar separación EMA como confianza
            resultado=resultado,
            numero_contrato=str(contract_id_real),  # SIEMPRE numérico, nunca PEND-
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            beneficio=beneficio,
            es_simulada=False,
        )
        
        # Registrar resultado
        self.gestor_core.registrar_resultado_operacion(operacion)
        from trading.scheduler import actualizar_rendimiento_horario
        actualizar_rendimiento_horario(mejor_activo, operacion)
        
        self.gestor_core.finalizar_operacion()
        
        # CRÍTICO: Ejecutar operación inversa INMEDIATAMENTE (mismo activo, dirección opuesta)
        # Esto asegura que ambas operaciones se ejecuten al mismo tiempo
        try:
            from trading_inverso.services import MotorTradingInverso
            motor_inverso = MotorTradingInverso()
            operacion_inversa = motor_inverso.ejecutar_ciclo_inverso(operacion)
            if operacion_inversa:
                self._enviar_evento({
                    "tipo": "info",
                    "mensaje": f"✅ Operación inversa ejecutada simultáneamente: {operacion_inversa.numero_contrato}",
                })
        except Exception as e:
            # Si falla el bot inverso, no interrumpir el flujo del bot principal
            self._enviar_evento({
                "tipo": "warning",
                "mensaje": f"⚠️ No se pudo ejecutar operación inversa: {e}",
            })
        
        # Sincronizar balance DESPUÉS de registrar la operación
        self.gestor_core.sincronizar_balance_desde_api()
        
        # Emitir evento con información completa
        self._emitir_evento_operacion(operacion)
        
        # Actualizar dashboard
        try:
            from dashboard.services import enviar_actualizacion_dashboard
            enviar_actualizacion_dashboard()
        except Exception:
            pass
        
        # Forzar actualización del historial en el frontend
        self._enviar_evento({
            "tipo": "actualizar_historial",
            "actualizar_panel": True,
        })
        
        return operacion

    def _emitir_evento_operacion(self, operacion: Operacion) -> None:
        """Emite evento de operación completada."""
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
                "hora_inicio": operacion.hora_inicio.isoformat() if operacion.hora_inicio else None,
                "hora_fin": operacion.hora_fin.isoformat() if operacion.hora_fin else None,
            },
        }
        self._enviar_evento(data)
