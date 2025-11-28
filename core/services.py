from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from historial.models import AjusteBalance, Operacion
from integracion_deriv.client import obtener_balance_sync

from .models import ConfiguracionBot


@dataclass
class EstadoBot:
    balance_actual: Decimal
    stop_loss_actual: Decimal
    estado: str
    activo_seleccionado: str
    perdida_acumulada: Decimal
    ganancia_acumulada: Decimal
    en_operacion: bool
    pausado_desde: Optional[datetime]
    pausa_finaliza: Optional[datetime]
    mejor_horario: Optional[time]
    ultima_simulacion: Optional[datetime]


class GestorBotCore:
    """
    Servicio principal para manejar la configuración dinámica del bot,
    incluyendo balance, metas y pausas.
    """

    def __init__(self) -> None:
        self.configuracion = ConfiguracionBot.obtener()

    def obtener_estado(self) -> EstadoBot:
        config = self.configuracion
        return EstadoBot(
            balance_actual=config.balance_actual,
            stop_loss_actual=config.stop_loss_actual,
            estado=config.estado,
            activo_seleccionado=config.activo_seleccionado,
            perdida_acumulada=config.perdida_acumulada,
            ganancia_acumulada=config.ganancia_acumulada,
            en_operacion=config.en_operacion,
            pausado_desde=config.pausado_desde,
            pausa_finaliza=config.pausa_finaliza,
            mejor_horario=config.mejor_horario,
            ultima_simulacion=config.ultima_simulacion,
        )

    @transaction.atomic
    def inicializar_balance(self, balance_inicial: Decimal) -> ConfiguracionBot:
        self.configuracion.balance_actual = balance_inicial.quantize(Decimal("0.01"))
        self.configuracion.ganancia_acumulada = Decimal("0.00")
        self.configuracion.perdida_acumulada = Decimal("0.00")
        self.configuracion.estado = ConfiguracionBot.Estado.OPERANDO
        self.configuracion.en_operacion = False
        self.configuracion.balance_meta_base = self.configuracion.balance_actual
        self.configuracion.balance_stop_loss_base = self.configuracion.balance_actual
        self.configuracion.stop_loss_actual = self.configuracion.calcular_stop_loss(
            self.configuracion.balance_stop_loss_base
        )
        self.configuracion.meta_actual = Decimal("0.00")
        self.configuracion.save(
            update_fields=[
                "balance_actual",
                "ganancia_acumulada",
                "perdida_acumulada",
                "estado",
                "en_operacion",
                "balance_meta_base",
                "balance_stop_loss_base",
                "stop_loss_actual",
                "meta_actual",
                "ultima_actualizacion",
            ]
        )
        return self.configuracion

    def obtener_monto_trade(self) -> Decimal:
        return self.configuracion.calcular_monto_trade()

    def marcar_operacion_en_curso(self, activo: str) -> None:
        self.configuracion.en_operacion = True
        self.configuracion.activo_seleccionado = activo
        self.configuracion.save(update_fields=["en_operacion", "activo_seleccionado", "ultima_actualizacion"])

    def finalizar_operacion(self) -> None:
        self.configuracion.en_operacion = False
        self.configuracion.save(update_fields=["en_operacion", "ultima_actualizacion"])

    def registrar_resultado_operacion(self, operacion: Operacion) -> None:
        if operacion.resultado == Operacion.Resultado.GANADA:
            self.configuracion.registrar_ganancia(operacion.beneficio)
        elif operacion.resultado == Operacion.Resultado.PERDIDA:
            # Si el beneficio es 0, es un empate (no se registra pérdida)
            if operacion.beneficio < 0:
                self.configuracion.registrar_perdida(abs(operacion.beneficio))
                self._verificar_stop_loss()
            # Si beneficio == 0, no hacer nada (empate, recuperas tu dinero)

    def _verificar_stop_loss(self) -> None:
        """
        Verifica si el balance actual llegó al stop loss (balance mínimo).
        El stop loss es un balance mínimo que nunca baja, solo sube.
        
        MEJORA: No pausa inmediatamente después de una operación ganada para evitar
        pausas prematuras causadas por discrepancias temporales de balance.
        """
        if self.configuracion.balance_actual <= self.configuracion.stop_loss_actual:
            # Verificar si la última operación fue ganada (evitar pausa inmediata después de win)
            from historial.models import Operacion
            from django.utils import timezone
            from datetime import timedelta
            
            ultima_operacion = Operacion.objetos.reales().order_by('-hora_inicio').first()
            
            # Si la última operación fue ganada hace menos de 2 minutos, NO pausar todavía
            # Esto evita pausas prematuras por discrepancias temporales de balance
            if ultima_operacion and ultima_operacion.resultado == Operacion.Resultado.GANADA:
                tiempo_desde_operacion = timezone.now() - ultima_operacion.hora_inicio
                if tiempo_desde_operacion < timedelta(minutes=2):
                    # Esperar al menos 2 minutos después de una ganada antes de pausar
                    # Esto da tiempo a que se sincronice correctamente el balance
                    return
            
            # Si pasó el tiempo o la última fue pérdida, proceder con la pausa
            self.configuracion.pausar()
            self.configuracion.mejor_horario = None
            self.configuracion.save(update_fields=["mejor_horario"])
            # Notificar pausa
            try:
                from notificaciones.services import ServicioNotificaciones

                ServicioNotificaciones().notificar_stop_loss(self.configuracion)
            except Exception:
                # Evitamos que un error en notificaciones rompa el flujo principal
                pass

    def debe_reanudar(self) -> bool:
        if self.configuracion.estado != ConfiguracionBot.Estado.PAUSADO:
            return False
        if not self.configuracion.pausa_finaliza:
            return False
        ahora = timezone.now()
        if ahora < self.configuracion.pausa_finaliza:
            return False
        if self.configuracion.mejor_horario:
            hora_objetivo = self.configuracion.mejor_horario
            hora_actual = timezone.localtime(ahora).time()
            if hora_actual < hora_objetivo:
                return False
        return True

    def reanudar_operativa(self) -> None:
        self.configuracion.reanudar()
        try:
            from notificaciones.services import ServicioNotificaciones

            ServicioNotificaciones().notificar_inicio_operativa(self.configuracion)
        except Exception:
            pass

    def calcular_balance_esperado_desde_operaciones(
        self, balance_inicial: Optional[Decimal] = None
    ) -> Decimal:
        """
        Calcula el balance esperado sumando todos los beneficios de las operaciones reales.
        Si no se proporciona balance_inicial, usa el balance_meta_base como punto de partida.
        """
        if balance_inicial is None:
            balance_inicial = (
                self.configuracion.balance_meta_base
                if self.configuracion.balance_meta_base > 0
                else self.configuracion.balance_actual
            )

        # Sumar todos los beneficios de operaciones reales (no simuladas)
        operaciones_reales = Operacion.objetos.reales().exclude(
            resultado=Operacion.Resultado.PENDIENTE
        )
        total_beneficios = sum(
            op.beneficio for op in operaciones_reales
        )
        balance_esperado = (balance_inicial + total_beneficios).quantize(Decimal("0.01"))
        return balance_esperado

    def detectar_discrepancia_balance(
        self, balance_real: Decimal, balance_esperado: Decimal, umbral: Decimal = Decimal("0.01")
    ) -> Optional[Decimal]:
        """
        Detecta si hay una discrepancia significativa entre el balance real y el esperado.
        Retorna la diferencia si es mayor al umbral, None en caso contrario.
        """
        diferencia = (balance_real - balance_esperado).quantize(Decimal("0.01"))
        if abs(diferencia) > umbral:
            return diferencia
        return None

    def registrar_ajuste_balance(
        self,
        balance_esperado: Decimal,
        balance_real: Decimal,
        diferencia: Decimal,
        descripcion: str = "",
    ) -> AjusteBalance:
        """
        Registra un ajuste de balance cuando se detecta una discrepancia.
        """
        balance_anterior = self.configuracion.balance_actual
        ajuste = AjusteBalance.objects.create(
            balance_esperado=balance_esperado,
            balance_real=balance_real,
            diferencia=diferencia,
            descripcion=descripcion or f"Discrepancia detectada: balance real ({balance_real}) vs esperado ({balance_esperado})",
            balance_anterior=balance_anterior,
        )
        return ajuste

    def sincronizar_balance_desde_api(self) -> None:
        if not self.configuracion:
            return
        try:
            respuesta = obtener_balance_sync()
        except Exception:
            return

        balance_info = respuesta.get("balance")
        if not balance_info:
            return

        balance = Decimal(str(balance_info.get("balance", "0")))
        if balance <= 0:
            return

        balance = balance.quantize(Decimal("0.01"))
        balance_anterior = self.configuracion.balance_actual

        # Calcular balance esperado desde operaciones registradas
        balance_esperado = self.calcular_balance_esperado_desde_operaciones()
        
        # Detectar discrepancias (umbral mínimo de $0.01 para evitar ruido)
        diferencia = self.detectar_discrepancia_balance(
            balance_real=balance,
            balance_esperado=balance_esperado,
            umbral=Decimal("0.01")
        )

        # Si hay discrepancia significativa, registrar el ajuste
        if diferencia is not None:
            descripcion = (
                f"Balance real de Deriv: {balance}, "
                f"Balance esperado desde operaciones: {balance_esperado}. "
                f"Diferencia: {diferencia}. "
                f"Esto puede deberse a comisiones, fees, o ajustes no contabilizados."
            )
            self.registrar_ajuste_balance(
                balance_esperado=balance_esperado,
                balance_real=balance,
                diferencia=diferencia,
                descripcion=descripcion,
            )

        self.configuracion.balance_actual = balance

        if self.configuracion.balance_meta_base <= 0:
            self.configuracion.balance_meta_base = balance
        if self.configuracion.balance_stop_loss_base <= 0:
            self.configuracion.balance_stop_loss_base = balance
            # Solo inicializar stop_loss si no existe
            if self.configuracion.stop_loss_actual <= 0:
                self.configuracion.stop_loss_actual = self.configuracion.calcular_stop_loss(balance)

        # NUEVA LÓGICA: El stop loss siempre debe estar al 95% del balance de Deriv
        # Si el balance sube, el stop loss sube (trailing stop loss)
        # Si el balance baja, el stop loss NO baja (se mantiene fijo como arnés de seguridad)
        # Solo actualizar si el bot está OPERANDO (no durante pausa)
        if self.configuracion.estado == ConfiguracionBot.Estado.OPERANDO:
            nuevo_stop_loss = self.configuracion.calcular_stop_loss(balance)
            # Solo actualizar si el nuevo stop loss es MAYOR que el actual (trailing)
            if nuevo_stop_loss > self.configuracion.stop_loss_actual:
                self.configuracion.stop_loss_actual = nuevo_stop_loss
                self.configuracion.balance_stop_loss_base = balance
            # Si el balance baja, el stop_loss_actual NO cambia (se mantiene fijo)
        
        self.configuracion.meta_actual = Decimal("0.00")

        # Actualizar pérdida acumulada (solo para estadísticas)
        perdida = self.configuracion.balance_stop_loss_base - balance
        if perdida < 0:
            perdida = Decimal("0.00")
        self.configuracion.perdida_acumulada = perdida.quantize(Decimal("0.01"))
        
        campos_actualizar = [
            "balance_actual",
            "perdida_acumulada",
            "meta_actual",
            "ultima_actualizacion",
        ]
        # Solo actualizar balance_stop_loss_base y stop_loss_actual si se inicializaron o actualizaron
        if self.configuracion.balance_stop_loss_base > 0:
            campos_actualizar.append("balance_stop_loss_base")
        if self.configuracion.stop_loss_actual > 0:
            campos_actualizar.append("stop_loss_actual")
        
        self.configuracion.save(update_fields=campos_actualizar)
        
        # CRÍTICO: Verificar stop loss después de sincronizar balance
        # PERO solo si el bot está OPERANDO (no si ya está pausado)
        # Y solo si el balance realmente cayó por debajo del stop loss
        # _verificar_stop_loss() ahora tiene protección para no pausar inmediatamente después de ganadas
        if self.configuracion.estado == ConfiguracionBot.Estado.OPERANDO:
            # Solo verificar si el balance está realmente por debajo del stop loss
            # Esto evita pausas incorrectas durante sincronizaciones
            if self.configuracion.balance_actual <= self.configuracion.stop_loss_actual:
                self._verificar_stop_loss()

    def ejecutar_trade_simulado_pausa(self) -> Optional[Operacion]:
        """
        Ejecuta un trade simulado durante la pausa.
        Usa precios reales de ticks históricos pero NO usa capital real (es_simulada=True).
        El trade se guarda en la BD para análisis posterior y priorización de activos/horarios.
        """
        if self.configuracion.estado != ConfiguracionBot.Estado.PAUSADO:
            return None
        
        try:
            from trading.services_profesional import MotorTradingProfesional
            from historial.models import Tick
            
            motor = MotorTradingProfesional()
            
            # Obtener la mejor señal sin ejecutar el trade real
            resultados = motor._evaluar_activos()
            if not resultados:
                return None
            
            mejor_resultado = resultados[0]
            mejor_activo = mejor_resultado["activo"]
            mejor_indicadores = mejor_resultado["indicadores"]
            mejor_score = mejor_resultado["score"]
            
            # Validar que la separación EMA es suficiente (umbral mínimo)
            if mejor_score < motor.umbral_separacion_pct:
                return None
            
            # Determinar dirección (ya viene de los indicadores EMA)
            direccion_str = mejor_indicadores.direccion_sugerida
            if direccion_str == "NONE" or not direccion_str:
                return None
            
            direccion = Operacion.Direccion.CALL if direccion_str == "CALL" else Operacion.Direccion.PUT
            
            # Aplicar modo inverso si está activo
            config = self.configuracion
            if config.modo_inverso:
                direccion = Operacion.Direccion.PUT if direccion == Operacion.Direccion.CALL else Operacion.Direccion.CALL
            
            # Obtener ticks históricos recientes (últimos 2 minutos para simular 60 segundos)
            ahora = timezone.now()
            desde = ahora - timedelta(minutes=2)
            ticks = list(Tick.objects.filter(
                activo=mejor_activo.nombre,
                epoch__gte=desde
            ).order_by("epoch")[:120])  # Máximo 120 ticks (2 minutos)
            
            if len(ticks) < 60:  # Necesitamos al menos 60 ticks para simular 60 segundos
                return None
            
            # Simular trade: precio de entrada (hace 60 ticks) y precio de cierre (ahora)
            tick_entrada = ticks[0] if len(ticks) >= 60 else ticks[-60]
            tick_cierre = ticks[-1]
            
            precio_entrada = tick_entrada.precio
            precio_cierre = tick_cierre.precio
            
            # Determinar resultado
            if direccion == Operacion.Direccion.CALL:
                resultado = Operacion.Resultado.GANADA if precio_cierre > precio_entrada else Operacion.Resultado.PERDIDA
            else:
                resultado = Operacion.Resultado.GANADA if precio_cierre < precio_entrada else Operacion.Resultado.PERDIDA
            
            # Calcular beneficio simulado (no afecta el balance real)
            monto_simulado = self.configuracion.calcular_monto_trade()
            if resultado == Operacion.Resultado.GANADA:
                beneficio = monto_simulado * Decimal("0.80")  # 80% de ganancia típica
            else:
                beneficio = -monto_simulado
            
            # Crear operación simulada
            numero_contrato = f"SIM-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            operacion = Operacion.objects.create(
                activo=mejor_activo.nombre,
                direccion=direccion,
                precio_entrada=precio_entrada,
                precio_cierre=precio_cierre,
                monto_invertido=Decimal("0.00"),  # No se invierte capital real
                confianza=mejor_score,
                resultado=resultado,
                numero_contrato=numero_contrato,
                hora_inicio=tick_entrada.epoch,
                hora_fin=tick_cierre.epoch,
                beneficio=beneficio,
                es_simulada=True,
            )
            
            # Actualizar estadísticas de activos y horarios para priorización
            from trading.scheduler import actualizar_rendimiento_horario
            actualizar_rendimiento_horario(mejor_activo, operacion)
            
            return operacion
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error ejecutando trade simulado durante pausa: {e}", exc_info=True)
            return None

    def ejecutar_simulacion_pausa(self, intervalo_segundos: int = 60):
        """
        Ejecuta simulaciones mientras el bot está en pausa.
        Por defecto, ejecuta una simulación cada 60 segundos para mantener
        los datos actualizados continuamente.
        
        NUEVO: También ejecuta trades simulados (sin capital real) para analizar
        horarios y activos con mejor desempeño.
        """
        if self.configuracion.estado != ConfiguracionBot.Estado.PAUSADO:
            return None

        ahora = timezone.now()
        ultima = self.configuracion.ultima_simulacion
        if ultima and (ahora - ultima) < timedelta(seconds=intervalo_segundos):
            return None

        # Ejecutar trade simulado (precios reales, sin capital real)
        trade_simulado = self.ejecutar_trade_simulado_pausa()
        
        # También ejecutar simulación de horarios (análisis histórico)
        try:
            from simulacion.services import SimuladorHorariosService

            simulador = SimuladorHorariosService()
            resultado = simulador.ejecutar()
        except Exception as e:
            # Log del error para debugging pero no interrumpir el loop
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error ejecutando simulación de horarios: {e}", exc_info=True)
            resultado = None

        if resultado or trade_simulado:
            self.configuracion.ultima_simulacion = ahora
            self.configuracion.save(update_fields=["ultima_simulacion", "ultima_actualizacion"])
        
        return resultado
