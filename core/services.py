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
    meta_actual: Decimal
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
            meta_actual=config.meta_actual,
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
        self.configuracion.meta_actual = self.configuracion.calcular_meta(
            self.configuracion.balance_meta_base
        )
        self.configuracion.stop_loss_actual = self.configuracion.calcular_stop_loss(
            self.configuracion.balance_stop_loss_base
        )
        self.configuracion.save(
            update_fields=[
                "balance_actual",
                "ganancia_acumulada",
                "perdida_acumulada",
                "estado",
                "en_operacion",
                "balance_meta_base",
                "balance_stop_loss_base",
                "meta_actual",
                "stop_loss_actual",
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
            self.configuracion.registrar_perdida(abs(operacion.beneficio))
            self._verificar_stop_loss()

    def _verificar_stop_loss(self) -> None:
        if self.configuracion.perdida_acumulada >= self.configuracion.stop_loss_actual:
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

        if balance > self.configuracion.balance_stop_loss_base:
            self.configuracion.balance_stop_loss_base = balance

        meta_base = self.configuracion.balance_meta_base
        meta_valor = self.configuracion.calcular_meta(meta_base)
        if balance - meta_base >= meta_valor:
            self.configuracion.balance_meta_base = balance
            meta_base = balance
            meta_valor = self.configuracion.calcular_meta(meta_base)

        self.configuracion.meta_actual = meta_valor
        self.configuracion.stop_loss_actual = self.configuracion.calcular_stop_loss(
            self.configuracion.balance_stop_loss_base
        )

        perdida = self.configuracion.balance_stop_loss_base - balance
        if perdida < 0:
            perdida = Decimal("0.00")
        self.configuracion.perdida_acumulada = perdida.quantize(Decimal("0.01"))
        self.configuracion.save(
            update_fields=[
                "balance_actual",
                "balance_meta_base",
                "balance_stop_loss_base",
                "meta_actual",
                "stop_loss_actual",
                "perdida_acumulada",
                "ultima_actualizacion",
            ]
        )

    def ejecutar_simulacion_pausa(self, intervalo_segundos: int = 3600):
        if self.configuracion.estado != ConfiguracionBot.Estado.PAUSADO:
            return None

        ahora = timezone.now()
        ultima = self.configuracion.ultima_simulacion
        if ultima and (ahora - ultima) < timedelta(seconds=intervalo_segundos):
            return None

        try:
            from simulacion.services import SimuladorHorariosService

            simulador = SimuladorHorariosService()
            resultado = simulador.ejecutar()
        except Exception:
            return None

        if resultado:
            self.configuracion.ultima_simulacion = ahora
            self.configuracion.save(update_fields=["ultima_simulacion", "ultima_actualizacion"])
        return resultado

