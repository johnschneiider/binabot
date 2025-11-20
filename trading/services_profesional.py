"""
Motor de trading profesional con análisis multi-activo optimizado.
Reemplaza el sistema simple basado en 2 ticks por un análisis robusto.
"""
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
from trading.database import actualizar_tick_cache, obtener_ticks_cache
from trading.database.cache_manager import actualizar_indicadores_activo
from trading.models import IndicadoresActivo
from trading.ranking import calcular_score_activo
# determinar_direccion se define al final del archivo
from trading.risk import (
    calcular_monto_adaptativo,
    crear_cooldown,
    detectar_micro_congestion,
    verificar_cooldown,
    verificar_limites_activo,
)
from trading.scheduler import obtener_confianza_horaria
from trading.utils import priorizar_activos_por_horario
from trading.signals import (
    calcular_consistencia,
    calcular_ema,
    calcular_fuerza_movimiento,
    calcular_momentum,
    calcular_rate_of_change,
    calcular_volatilidad,
)


class MotorTradingProfesional:
    """
    Motor de trading profesional con análisis multi-activo.
    Evalúa 88 activos simultáneamente usando indicadores técnicos avanzados.
    """

    def __init__(self) -> None:
        self.gestor_core = GestorBotCore()
        self.channel_layer = get_channel_layer()
        self.ultimo_mensaje_diagnostico = None  # Para logging detallado
        
        # Configuración
        self.periodo_analisis = 20  # Ticks a analizar
        self.umbral_score_minimo = Decimal("40.00")
        self.umbral_consistencia = Decimal("30.00")
        self.umbral_volatilidad_minima = Decimal("0.001")
        self.umbral_confianza_horaria = Decimal("45.00")

    def _enviar_evento(self, data: Dict) -> None:
        """Envía evento a través de WebSockets."""
        # Guardar mensajes de info/error para diagnóstico
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
        Calcula todos los indicadores técnicos para un activo.
        
        Returns:
            Diccionario con indicadores o None si no hay datos suficientes
        """
        # Actualizar cache de ticks
        actualizar_tick_cache(activo, max_ticks=self.periodo_analisis)
        
        # Obtener ticks desde cache
        precios = obtener_ticks_cache(activo, cantidad=self.periodo_analisis)
        
        if len(precios) < 10:
            return None
        
        # Calcular indicadores
        momentum_simple, momentum_pct = calcular_momentum(precios, periodo=10)
        volatilidad = calcular_volatilidad(precios, periodo=20)
        ema = calcular_ema(precios, periodo=10)
        roc = calcular_rate_of_change(precios, periodo=10)
        consistencia = calcular_consistencia(precios, periodo=10)
        
        precio_actual = precios[-1]
        fuerza_movimiento = calcular_fuerza_movimiento(precio_actual, ema)
        
        # Determinar dirección usando función local
        direccion = determinar_direccion_simple(precios, ema, roc)
        
        return {
            "momentum_simple": momentum_simple,
            "momentum_pct": momentum_pct,
            "volatilidad": volatilidad,
            "tendencia_ema": ema,
            "precio_actual": precio_actual,
            "rate_of_change": roc,
            "fuerza_movimiento": fuerza_movimiento,
            "consistencia": consistencia,
            "direccion_sugerida": direccion,
            "ticks_analizados": len(precios),
        }

    def _evaluar_activos(self) -> List[Dict]:
        """
        Evalúa todos los activos habilitados y calcula sus scores.
        
        Returns:
            Lista de activos con sus indicadores y scores, ordenados por score
        """
        activos = priorizar_activos_por_horario(
            list(ActivoPermitido.objects.filter(habilitado=True))
        )
        resultados = []
        
        activos_evaluados = 0
        activos_rechazados_cooldown = 0
        activos_rechazados_limites = 0
        activos_rechazados_indicadores = 0
        activos_rechazados_volatilidad = 0
        activos_rechazados_consistencia = 0
        activos_rechazados_microcongestion = 0
        
        for activo in activos:
            activos_evaluados += 1
            # Verificar cooldown
            if not verificar_cooldown(activo.id):
                activos_rechazados_cooldown += 1
                continue
            
            # Verificar límites
            if not verificar_limites_activo(activo.nombre):
                activos_rechazados_limites += 1
                continue
            
            # Calcular indicadores
            indicadores_data = self._calcular_indicadores_activo(activo)
            if not indicadores_data:
                activos_rechazados_indicadores += 1
                continue
            
            # Verificar umbrales mínimos
            if indicadores_data["volatilidad"] < self.umbral_volatilidad_minima:
                activos_rechazados_volatilidad += 1
                continue
            
            if indicadores_data["consistencia"] < self.umbral_consistencia:
                activos_rechazados_consistencia += 1
                continue
            
            # Guardar indicadores
            indicadores, _ = IndicadoresActivo.objects.update_or_create(
                activo=activo,
                defaults=indicadores_data,
            )
            
            # Calcular score
            from trading.models import RendimientoActivo
            
            try:
                rendimiento = RendimientoActivo.objects.filter(
                    activo=activo
                ).order_by("-winrate_dinamico").first()
            except RendimientoActivo.DoesNotExist:
                rendimiento = None
            
            score = calcular_score_activo(
                indicadores,
                rendimiento=rendimiento,
                umbral_minimo=self.umbral_score_minimo,
            )
            
            # Verificar confianza horaria
            confianza_horaria = obtener_confianza_horaria(activo)
            if confianza_horaria < self.umbral_confianza_horaria:
                score = score * Decimal("0.5")  # Reducir score si horario no es óptimo
            
            # Actualizar score en indicadores
            indicadores.score_total = score
            indicadores.save()
            
            # Verificar micro-congestión
            if detectar_micro_congestion(indicadores):
                activos_rechazados_microcongestion += 1
                crear_cooldown(
                    activo.id,
                    motivo="Micro-congestion detectada",  # Truncado a 40 chars
                    duracion_minutos=5,
                )
                continue
            
            resultados.append({
                "activo": activo,
                "indicadores": indicadores,
                "score": score,
                "confianza_horaria": confianza_horaria,
            })
        
        # Ordenar por score descendente
        resultados.sort(key=lambda x: x["score"], reverse=True)
        
        # Log detallado de evaluación (solo si no hay resultados para diagnóstico)
        if not resultados:
            mensaje_detallado = (
                f"Evaluación: Total={activos_evaluados}, "
                f"Cooldown={activos_rechazados_cooldown}, "
                f"Límites={activos_rechazados_limites}, "
                f"Sin indicadores={activos_rechazados_indicadores}, "
                f"Volatilidad baja={activos_rechazados_volatilidad}, "
                f"Consistencia baja={activos_rechazados_consistencia}, "
                f"Micro-congestión={activos_rechazados_microcongestion}"
            )
            self._enviar_evento({
                "tipo": "info",
                "mensaje": mensaje_detallado,
            })
        
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
            "mensaje": "Evaluando activos disponibles...",
        })
        
        resultados = self._evaluar_activos()
        
        if not resultados:
            # Obtener información detallada sobre por qué no hay resultados
            activos_habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
            from trading.models import CooldownActivo
            cooldowns_activos = CooldownActivo.objects.filter(finaliza_en__gt=timezone.now()).count()
            
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"No se encontraron activos con señales válidas. Activos habilitados: {activos_habilitados}, Cooldowns activos: {cooldowns_activos}",
            })
            return None
        
        # Seleccionar el mejor activo (Top 1)
        mejor_resultado = resultados[0]
        mejor_activo = mejor_resultado["activo"]
        mejor_indicadores = mejor_resultado["indicadores"]
        mejor_score = mejor_resultado["score"]
        
        if mejor_score < self.umbral_score_minimo:
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"Score máximo ({mejor_score}) no alcanza el umbral mínimo ({self.umbral_score_minimo}). Activo: {mejor_activo.nombre}",
            })
            return None
        
        # Determinar dirección final
        direccion = mejor_indicadores.direccion_sugerida
        if direccion == "NONE":
            # Usar múltiples factores para decidir
            if mejor_indicadores.momentum_pct > 0:
                direccion = "CALL"
            elif mejor_indicadores.momentum_pct < 0:
                direccion = "PUT"
            else:
                self._enviar_evento({
                    "tipo": "info",
                    "mensaje": "No se pudo determinar dirección clara.",
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
            # Log también en stdout para que aparezca en los logs del sistema
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
        
        # Crear operación
        import uuid
        # Generar número de contrato truncado a 40 caracteres máximo
        uuid_str = str(uuid.uuid4()).replace("-", "")  # UUID sin guiones (32 chars)
        numero_contrato = f"PEND-{uuid_str[:32]}"  # PEND- (5) + 32 chars = 37 chars total
        # Asegurar que no exceda 40 caracteres
        numero_contrato = numero_contrato[:40]
        
        operacion = Operacion.objetos.create(
            activo=mejor_activo.nombre,
            direccion=Operacion.Direccion.CALL if direccion == "CALL" else Operacion.Direccion.PUT,
            precio_entrada=mejor_indicadores.precio_actual,
            monto_invertido=monto_trade,
            confianza=mejor_score,
            resultado=Operacion.Resultado.PENDIENTE,
            numero_contrato=numero_contrato,
            hora_inicio=timezone.now(),
            es_simulada=False,
        )
        
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
                duration=5,
                duration_unit="t",
                contract_type=contract_type,
            )
            
            # Verificar errores en la respuesta
            if respuesta.get("error"):
                error_info = respuesta.get("error", {})
                raise Exception(f"Error de Deriv API: {error_info.get('message', 'Error desconocido')}")
            
            open_contract = respuesta.get("proposal_open_contract", {})
            if not open_contract:
                raise Exception(f"Respuesta inválida de Deriv: no se encontró proposal_open_contract. Respuesta: {respuesta}")
            
            status = open_contract.get("status")
            beneficio_api = Decimal(str(open_contract.get("profit", 0))).quantize(Decimal("0.01"))
            precio_cierre = Decimal(str(open_contract.get("sell_price", 0))).quantize(Decimal("0.00001"))
            
            # Obtener contract_id real de la respuesta (debe estar siempre presente)
            contract_id_real = open_contract.get("contract_id")
            if not contract_id_real:
                # Intentar obtener de la respuesta de compra si está disponible
                buy_response = respuesta.get("buy", {})
                contract_id_real = buy_response.get("contract_id")
            
            if contract_id_real:
                contract_id_str = str(contract_id_real)
                numero_final = contract_id_str[:40] if len(contract_id_str) > 40 else contract_id_str
            else:
                # Si aún no hay contract_id, es un error crítico
                raise Exception(f"No se recibió contract_id de Deriv. Respuesta completa: {respuesta}")
            
            # Determinar resultado basado en el beneficio real de la API
            # Si profit == 0, es un empate (recuperas tu dinero, no ganas ni pierdes)
            # Si profit > 0, es ganancia
            # Si profit < 0, es pérdida
            if beneficio_api > 0:
                resultado = Operacion.Resultado.GANADA
            elif beneficio_api < 0:
                resultado = Operacion.Resultado.PERDIDA
            else:
                # profit == 0: empate (recuperas tu dinero)
                # Deriv puede marcar esto como "lost" pero el profit es 0
                # Lo tratamos como pérdida para estadísticas, pero beneficio = 0
                resultado = Operacion.Resultado.PERDIDA
            
            beneficio = beneficio_api
            
        except Exception as exc:
            self._enviar_evento({"tipo": "error", "mensaje": str(exc)})
            resultado = Operacion.Resultado.PERDIDA
            beneficio = -monto_trade
            precio_cierre = operacion.precio_entrada
            numero_final = numero_contrato
        
        # Actualizar operación
        operacion.resultado = resultado
        operacion.beneficio = beneficio
        operacion.precio_cierre = precio_cierre
        operacion.hora_fin = timezone.now()
        operacion.numero_contrato = numero_final
        operacion.save()
        
        # Registrar resultado y actualizar rendimiento horario
        self.gestor_core.registrar_resultado_operacion(operacion)
        from trading.scheduler import actualizar_rendimiento_horario
        actualizar_rendimiento_horario(mejor_activo, operacion)
        
        self.gestor_core.finalizar_operacion()
        
        # Emitir evento
        self._emitir_evento_operacion(operacion)
        
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


def determinar_direccion_simple(
    precios: List[Decimal],
    ema: Decimal,
    roc: Decimal,
) -> str:
    """
    Determina dirección usando múltiples factores.
    
    Args:
        precios: Lista de precios
        ema: Valor de EMA
        roc: Rate of Change
    
    Returns:
        "CALL", "PUT" o "NONE"
    """
    precio_actual = precios[-1]
    
    factores_call = 0
    factores_put = 0
    
    # Factor 1: EMA vs Precio
    if ema > precio_actual:
        factores_call += 1
    elif ema < precio_actual:
        factores_put += 1
    
    # Factor 2: ROC
    if roc > 0:
        factores_call += 1
    elif roc < 0:
        factores_put += 1
    
    # Factor 3: Momentum reciente
    if len(precios) >= 5:
        momentum_reciente = precios[-1] - precios[-5]
        if momentum_reciente > 0:
            factores_call += 1
        elif momentum_reciente < 0:
            factores_put += 1
    
    if factores_call > factores_put:
        return "CALL"
    elif factores_put > factores_call:
        return "PUT"
    else:
        return "NONE"

