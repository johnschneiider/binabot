from collections import defaultdict
from dataclasses import dataclass
from datetime import time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from core.models import ActivoPermitido
from core.services import GestorBotCore
from historial.models import Operacion, Tick

from .models import ResultadoHorarioSimulacion


@dataclass
class ResultadoHorario:
    hora: time
    winrate: Decimal
    total_operaciones: int
    ganadas: int
    perdidas: int


class SimuladorHorariosService:
    """
    Durante la pausa del bot se generan operaciones ficticias para evaluar
    el mejor horario de reactivación.
    """

    def __init__(
        self,
        operaciones_por_horario: int = 5,
        activo: Optional[str] = None,
        duracion_ticks: int = 5,
    ) -> None:
        self.operaciones_por_horario = operaciones_por_horario
        self.activo = activo
        self.duracion_ticks = max(1, duracion_ticks)
        self.channel_layer = get_channel_layer()

    def _obtener_activo(self) -> Optional[str]:
        if self.activo:
            return self.activo

        gestor = GestorBotCore()
        if gestor.configuracion.activo_seleccionado:
            return gestor.configuracion.activo_seleccionado

        activo_model = ActivoPermitido.objects.filter(habilitado=True).first()
        if activo_model:
            return activo_model.nombre
        ultimo_tick = Tick.objects.order_by("-epoch").first()
        if ultimo_tick:
            return ultimo_tick.activo
        return None

    def _agrupar_ticks_por_hora(
        self, ticks: List[Tick], tz
    ) -> Dict[int, List[Tick]]:
        agrupados: Dict[int, List[Tick]] = defaultdict(list)
        for tick in ticks:
            hora_local = timezone.localtime(tick.epoch, tz).hour
            agrupados[hora_local].append(tick)
        return agrupados

    def _simular_operaciones_con_ticks(
        self, ticks: List[Tick], hora: int
    ) -> Dict[str, int]:
        ganadas = 0
        perdidas = 0
        if len(ticks) <= self.duracion_ticks:
            return {"ganadas": ganadas, "perdidas": perdidas}

        # Queremos varias operaciones por hora pero separadas entre sí
        paso = max(
            1,
            len(ticks)
            // max(self.operaciones_por_horario * 2, self.operaciones_por_horario + 1),
        )
        operaciones_generadas = 0

        for indice in range(1, len(ticks) - self.duracion_ticks):
            if operaciones_generadas >= self.operaciones_por_horario:
                break

            if indice % paso != 0:
                continue

            tick_inicio = ticks[indice]
            tick_prev = ticks[indice - 1]
            tick_salida = ticks[indice + self.duracion_ticks]

            precio_inicio = tick_inicio.precio
            precio_prev = tick_prev.precio
            precio_fin = tick_salida.precio

            # Determinar dirección basándonos en el momentum inmediato anterior
            if precio_inicio == precio_prev:
                # Si no hubo movimiento previo, asumimos dirección al alza como neutral
                direccion = Operacion.Direccion.CALL
            else:
                direccion = (
                    Operacion.Direccion.CALL
                    if precio_inicio > precio_prev
                    else Operacion.Direccion.PUT
                )

            if precio_fin == precio_inicio:
                resultado = Operacion.Resultado.PERDIDA
            elif (
                direccion == Operacion.Direccion.CALL and precio_fin > precio_inicio
            ) or (
                direccion == Operacion.Direccion.PUT and precio_fin < precio_inicio
            ):
                resultado = Operacion.Resultado.GANADA
            else:
                resultado = Operacion.Resultado.PERDIDA

            diferencia = (precio_fin - precio_inicio).quantize(Decimal("0.00001"))

            confianza = (
                (abs(diferencia) / precio_inicio * Decimal("100"))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            numero_contrato = (
                f"SIM-{int(tick_inicio.epoch.timestamp())}-{int(tick_salida.epoch.timestamp())}"
            )

            beneficio = (
                abs(diferencia)
                if resultado == Operacion.Resultado.GANADA
                else -abs(diferencia)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            Operacion.objetos.update_or_create(
                numero_contrato=numero_contrato,
                defaults={
                    "activo": tick_inicio.activo,
                    "direccion": direccion,
                    "precio_entrada": precio_inicio,
                    "precio_cierre": precio_fin,
                    "monto_invertido": Decimal("0.00"),
                    "confianza": confianza,
                    "resultado": resultado,
                    "hora_inicio": tick_inicio.epoch,
                    "hora_fin": tick_salida.epoch,
                    "beneficio": beneficio,
                    "es_simulada": True,
                },
            )

            if resultado == Operacion.Resultado.GANADA:
                ganadas += 1
            else:
                perdidas += 1
            operaciones_generadas += 1

        return {"ganadas": ganadas, "perdidas": perdidas}

    @transaction.atomic
    def ejecutar(self) -> Optional[ResultadoHorario]:
        simbolo = self._obtener_activo()
        if not simbolo:
            return None

        fin = timezone.now()
        inicio = fin - timedelta(hours=24)
        ticks = list(
            Tick.objects.filter(
                activo=simbolo,
                epoch__range=(inicio, fin),
            ).order_by("epoch")
        )
        if not ticks:
            return None

        tz = timezone.get_current_timezone()
        ticks_por_hora = self._agrupar_ticks_por_hora(ticks, tz)
        horas = [time(h, 0) for h in range(0, 24)]
        mejores_resultados: List[ResultadoHorario] = []

        for hora in horas:
            data_hora = ticks_por_hora.get(hora.hour, [])
            resultados = self._simular_operaciones_con_ticks(data_hora, hora.hour)
            ganadas = resultados["ganadas"]
            perdidas = resultados["perdidas"]
            total = ganadas + perdidas
            if total == 0:
                continue

            resultado_modelo = ResultadoHorarioSimulacion.crear_o_actualizar(
                hora_inicio=hora,
                ganadas=ganadas,
                perdidas=perdidas,
                fecha_calculo=timezone.now(),
            )
            mejores_resultados.append(
                ResultadoHorario(
                    hora=hora,
                    winrate=resultado_modelo.winrate,
                    total_operaciones=resultado_modelo.total_operaciones,
                    ganadas=ganadas,
                    perdidas=perdidas,
                )
            )

        if not mejores_resultados:
            return None
        mejor = max(
            mejores_resultados,
            key=lambda r: (r.winrate, r.total_operaciones),
        )

        gestor = GestorBotCore()
        gestor.configuracion.mejor_horario = mejor.hora
        gestor.configuracion.save(update_fields=["mejor_horario", "ultima_actualizacion"])

        if self.channel_layer:
            async_to_sync(self.channel_layer.group_send)(
                "deriv_estado",
                {
                    "type": "recibir_evento_deriv",
                    "data": {
                        "tipo": "simulacion",
                        "actualizar_panel": True,
                        "hora_optima": mejor.hora.strftime("%H:%M"),
                        "winrate": str(mejor.winrate),
                    },
                },
            )
        return mejor

