"""
Motor de trading profesional con análisis multi-activo optimizado.
Reemplaza el sistema simple basado en 2 ticks por un análisis robusto.
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
from trading.database import actualizar_tick_cache, obtener_ticks_cache
from trading.database.cache_manager import actualizar_indicadores_activo
from trading.models import IndicadoresActivo
# Estrategia simplificada - solo imports necesarios
from trading.risk import (
    calcular_monto_adaptativo,
    verificar_cooldown,
)
from trading.signals import (
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
        
        # Configuración SIMPLIFICADA - Estrategia simple basada en momentum
        # Menos filtros = menos overfitting, más operaciones
        self.duracion_trade_segundos = 60  # Duración del trade (debe coincidir con duration del contrato)
        self.periodo_analisis_segundos = 60  # Analizar los últimos 60 segundos (equivalente a la duración del trade)
        self.umbral_score_minimo = Decimal("15.00")  # Muy reducido: permitir más operaciones
        # Eliminados: umbral_consistencia, umbral_volatilidad_minima, umbral_confianza_horaria

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
        Calcula indicadores SIMPLIFICADOS: solo momentum y volatilidad básica.
        Analiza los últimos 60 segundos (equivalente a la duración del trade).
        Estrategia simple que funciona para todos los activos.
        
        Returns:
            Diccionario con indicadores o None si no hay datos suficientes
        """
        # Obtener ticks de los últimos 60 segundos directamente desde la BD
        # Esto asegura que el análisis sea equivalente a la duración del trade
        from historial.models import Tick
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
        
        # Mínimo de 2 ticks para calcular momentum (precio inicial y final)
        if len(precios) < 2:
            return None
        
        # ESTRATEGIA SIMPLE: Momentum en los últimos 60 segundos
        # Esto es equivalente a la duración del trade (60 segundos)
        precio_actual = precios[-1]
        precio_inicial = precios[0]
        
        momentum_simple = precio_actual - precio_inicial
        momentum_pct = (momentum_simple / precio_inicial * 100) if precio_inicial > 0 else Decimal("0")
        
        # Volatilidad simple: desviación estándar de los precios en el período
        volatilidad = calcular_volatilidad(precios, periodo=len(precios))
        
        # Dirección simple: basada solo en momentum
        # Si el precio subió en los últimos 60 segundos → CALL
        # Si el precio bajó en los últimos 60 segundos → PUT
        if momentum_pct > 0:
            direccion = "CALL"
        elif momentum_pct < 0:
            direccion = "PUT"
        else:
            direccion = "NONE"
        
        return {
            "momentum_simple": momentum_simple,
            "momentum_pct": momentum_pct,
            "volatilidad": volatilidad,
            "precio_actual": precio_actual,
            "direccion_sugerida": direccion,
            "ticks_analizados": len(precios),
        }

    def _evaluar_activos(self) -> List[Dict]:
        """
        Evalúa activos con estrategia MEJORADA basada en:
        - Momentum (últimos 60 segundos)
        - Winrate histórico del activo
        - Priorización de horarios óptimos
        
        Returns:
            Lista de activos con sus indicadores y scores, ordenados por score
        """
        from historial.models import Operacion
        from django.db.models import Count, Q
        from django.utils import timezone
        
        # Obtener activos habilitados
        activos = list(ActivoPermitido.objects.filter(habilitado=True))
        resultados = []
        
        # Calcular winrate histórico por activo
        winrates_historicos = {}
        for activo in activos:
            ops = Operacion.objetos.reales().filter(activo=activo.nombre)
            total = ops.count()
            if total >= 5:  # Mínimo 5 operaciones para considerar winrate
                ganadas = ops.filter(resultado=Operacion.Resultado.GANADA).count()
                winrate = (ganadas / total * 100) if total > 0 else 0
                winrates_historicos[activo.nombre] = winrate
            else:
                winrates_historicos[activo.nombre] = 50.0  # Neutral si no hay suficientes datos
        
        # Verificar horario actual
        hora_actual = timezone.localtime(timezone.now()).hour
        horario_optimo = hora_actual == 6  # 6:00 es el mejor horario según datos
        
        for activo in activos:
            # Solo verificar cooldown básico
            if not verificar_cooldown(activo.id):
                continue
            
            # FILTRAR activos con winrate muy bajo (<30%)
            winrate_historico = winrates_historicos.get(activo.nombre, 50.0)
            if winrate_historico < 30.0:
                continue  # Evitar activos problemáticos
            
            # Calcular indicadores básicos (momentum simple)
            indicadores_data = self._calcular_indicadores_activo(activo)
            if not indicadores_data:
                continue
            
            # Guardar indicadores
            indicadores, _ = IndicadoresActivo.objects.update_or_create(
                activo=activo,
                defaults=indicadores_data,
            )
            
            # Score MEJORADO: Momentum + Winrate histórico + Bonus horario
            momentum_score = abs(indicadores.momentum_pct) * Decimal("100")  # 0-100 basado en momentum
            volatilidad_score = min(indicadores.volatilidad * Decimal("1000"), Decimal("20"))  # Bonus por volatilidad
            
            # Bonus por winrate histórico (activos con mejor historial tienen más score)
            winrate_bonus = Decimal(str(winrate_historico)) - Decimal("50.0")  # -50 a +50
            winrate_bonus = max(winrate_bonus, Decimal("0"))  # Solo bonus positivo
            
            # Bonus por horario óptimo
            horario_bonus = Decimal("15.0") if horario_optimo else Decimal("0.0")
            
            score = momentum_score + volatilidad_score + winrate_bonus + horario_bonus
            
            # Actualizar score en indicadores
            indicadores.score_total = score
            indicadores.save()
            
            resultados.append({
                "activo": activo,
                "indicadores": indicadores,
                "score": score,
                "winrate_historico": winrate_historico,
            })
        
        # Ordenar por score descendente
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
            "mensaje": "Evaluando activos disponibles...",
        })
        
        resultados = self._evaluar_activos()
        
        if not resultados:
            activos_habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
            from trading.models import CooldownActivo
            cooldowns_activos = CooldownActivo.objects.filter(finaliza_en__gt=timezone.now()).count()
            
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"No se encontraron activos disponibles. Habilitados: {activos_habilitados}, En cooldown: {cooldowns_activos}",
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
        
        # Determinar dirección: basada en momentum
        # NOTA: Los datos muestran que las ganadas tienen momentum negativo
        # Esto sugiere reversión de tendencia - cuando el precio baja, luego sube (PUT gana)
        # Cuando el precio sube, luego baja (CALL pierde)
        # Por ahora mantenemos la lógica original pero con umbral mínimo de momentum
        direccion = mejor_indicadores.direccion_sugerida
        
        # Requerir momentum mínimo significativo (evitar ruido)
        momentum_abs = abs(mejor_indicadores.momentum_pct)
        if momentum_abs < Decimal("0.01"):  # Momentum muy pequeño, saltar
            self._enviar_evento({
                "tipo": "info",
                "mensaje": f"Momentum muy pequeño ({mejor_indicadores.momentum_pct:.4f}%) en {mejor_activo.nombre}. Esperando siguiente ciclo.",
            })
            return None
        
        if direccion == "NONE":
            # Fallback: usar momentum directamente
            if mejor_indicadores.momentum_pct > 0:
                direccion = "CALL"
            elif mejor_indicadores.momentum_pct < 0:
                direccion = "PUT"
            else:
                self._enviar_evento({
                    "tipo": "info",
                    "mensaje": f"Sin momentum claro en {mejor_activo.nombre}. Esperando siguiente ciclo.",
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
        
        contract_id_real = open_contract.get("contract_id") or respuesta.get("buy", {}).get("contract_id")
        if not contract_id_real:
            self._enviar_evento({
                "tipo": "error",
                "mensaje": f"No se recibió contract_id de Deriv. Respuesta: {respuesta}",
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
        
        operacion = Operacion.objetos.create(
            activo=mejor_activo.nombre,
            direccion=Operacion.Direccion.CALL if direccion == "CALL" else Operacion.Direccion.PUT,
            precio_entrada=precio_entrada,
            precio_cierre=precio_cierre,
            monto_invertido=monto_trade,
            confianza=mejor_score,
            resultado=resultado,
            numero_contrato=str(contract_id_real),
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            beneficio=beneficio,
            es_simulada=False,
        )
        
        # Registrar resultado y actualizar rendimiento horario
        self.gestor_core.registrar_resultado_operacion(operacion)
        from trading.scheduler import actualizar_rendimiento_horario
        actualizar_rendimiento_horario(mejor_activo, operacion)
        
        self.gestor_core.finalizar_operacion()
        
        # CRÍTICO: Sincronizar balance DESPUÉS de registrar la operación
        # Esto asegura que el balance y las operaciones estén sincronizados
        self.gestor_core.sincronizar_balance_desde_api()
        
        # Emitir evento con información completa
        self._emitir_evento_operacion(operacion)
        
        # También enviar actualización completa del dashboard con historial
        try:
            from dashboard.services import enviar_actualizacion_dashboard
            enviar_actualizacion_dashboard()
        except Exception:
            # Si falla, no interrumpir el flujo
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

