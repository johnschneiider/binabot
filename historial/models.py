from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.db import models
from django.utils import timezone


class OperacionQuerySet(models.QuerySet):
    def reales(self):
        return self.filter(es_simulada=False)

    def simuladas(self):
        return self.filter(es_simulada=True)

    def ganadas(self):
        return self.filter(resultado=Operacion.Resultado.GANADA)

    def perdidas(self):
        return self.filter(resultado=Operacion.Resultado.PERDIDA)


class Operacion(models.Model):
    class Direccion(models.TextChoices):
        CALL = "CALL", "CALL"
        PUT = "PUT", "PUT"

    class Resultado(models.TextChoices):
        GANADA = "win", "Ganada"
        PERDIDA = "loss", "Perdida"
        PENDIENTE = "pending", "Pendiente"

    activo = models.CharField(max_length=80)
    direccion = models.CharField(max_length=4, choices=Direccion.choices)
    precio_entrada = models.DecimalField(max_digits=12, decimal_places=5)
    precio_cierre = models.DecimalField(
        max_digits=12, decimal_places=5, null=True, blank=True
    )
    monto_invertido = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    confianza = models.DecimalField(
        "Porcentaje de confianza",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    resultado = models.CharField(
        max_length=10,
        choices=Resultado.choices,
        default=Resultado.PENDIENTE,
    )
    numero_contrato = models.CharField(max_length=40, unique=True)
    hora_inicio = models.DateTimeField(default=timezone.now)
    hora_fin = models.DateTimeField(null=True, blank=True)
    beneficio = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    es_simulada = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    objects = OperacionQuerySet.as_manager()
    objetos = objects

    class Meta:
        ordering = ("-hora_inicio",)
        verbose_name = "Operación"
        verbose_name_plural = "Operaciones"

    def __str__(self) -> str:
        return f"{self.activo} {self.direccion} #{self.numero_contrato}"

    @property
    def es_ganada(self) -> bool:
        return self.resultado == self.Resultado.GANADA

    @property
    def es_perdida(self) -> bool:
        return self.resultado == self.Resultado.PERDIDA


class Tick(models.Model):
    activo = models.CharField(max_length=80)
    epoch = models.DateTimeField()
    precio = models.DecimalField(max_digits=12, decimal_places=5)
    pip_size = models.PositiveIntegerField(default=0)
    datos = models.JSONField(default=dict, blank=True)
    recibido = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()

    class Meta:
        ordering = ("-epoch",)
        unique_together = ("activo", "epoch")
        indexes = [
            models.Index(fields=("activo", "epoch")),
        ]

    def __str__(self) -> str:
        return f"{self.activo} @ {self.epoch.isoformat()}"

    @classmethod
    def registrar_desde_payload(cls, tick: dict) -> "Tick":
        symbol = tick.get("symbol")
        epoch_segundos = tick.get("epoch")
        if not symbol or epoch_segundos is None:
            raise ValueError("El payload de tick no contiene 'symbol' o 'epoch'.")

        epoch_dt = datetime.fromtimestamp(epoch_segundos, tz=dt_timezone.utc)
        precio = Decimal(str(tick.get("quote", "0")))
        pip_size = tick.get("pip_size") or 0

        instancia, _ = cls.objects.update_or_create(
            activo=symbol,
            epoch=epoch_dt,
            defaults={
                "precio": precio,
                "pip_size": pip_size,
                "datos": tick,
            },
        )
        return instancia
