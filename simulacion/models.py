from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone


class ResultadoHorarioSimulacionQuerySet(models.QuerySet):
    def recientes(self):
        return self.order_by("-fecha_calculo")

    def mejor(self):
        return self.order_by("-winrate").first()


class ResultadoHorarioSimulacion(models.Model):
    activo = models.CharField(max_length=80, default="")
    hora_inicio = models.TimeField()
    total_operaciones = models.PositiveIntegerField(default=0)
    operaciones_ganadas = models.PositiveIntegerField(default=0)
    operaciones_perdidas = models.PositiveIntegerField(default=0)
    winrate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    fecha_calculo = models.DateTimeField(default=timezone.now)

    objects = models.Manager()
    objetos = ResultadoHorarioSimulacionQuerySet.as_manager()

    class Meta:
        verbose_name = "Resultado de simulación por horario"
        verbose_name_plural = "Resultados de simulación por horario"
        ordering = ("-fecha_calculo", "-winrate")
        unique_together = ("activo", "hora_inicio", "fecha_calculo")

    def __str__(self) -> str:
        return f"Horario {self.hora_inicio} - Winrate {self.winrate}%"

    @classmethod
    def crear_o_actualizar(
        cls,
        *,
        activo: str,
        hora_inicio,
        ganadas: int,
        perdidas: int,
        fecha_calculo=None,
    ):
        fecha_calculo = fecha_calculo or timezone.now()
        total = ganadas + perdidas
        if total == 0:
            winrate = Decimal("0.00")
        else:
            winrate = (Decimal(ganadas) / Decimal(total) * Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        objeto, _ = cls.objects.update_or_create(
            activo=activo,
            hora_inicio=hora_inicio,
            fecha_calculo=fecha_calculo,
            defaults={
                "total_operaciones": total,
                "operaciones_ganadas": ganadas,
                "operaciones_perdidas": perdidas,
                "winrate": winrate,
            },
        )
        return objeto
