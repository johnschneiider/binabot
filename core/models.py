from decimal import Decimal
from typing import Optional

from django.db import models
from django.utils import timezone


class ConfiguracionBot(models.Model):
    MONTO_TRADE_PORCENTAJE = Decimal("0.005")
    META_PORCENTAJE = Decimal("0.01")
    STOP_LOSS_PORCENTAJE = Decimal("0.02")

    class Estado(models.TextChoices):
        OPERANDO = "operando", "Operando"
        PAUSADO = "pausado", "Pausado"

    balance_actual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    meta_actual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    stop_loss_actual = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    estado = models.CharField(
        max_length=15, choices=Estado.choices, default=Estado.OPERANDO
    )
    activo_seleccionado = models.CharField(max_length=80, blank=True)
    perdida_acumulada = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    ganancia_acumulada = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    balance_meta_base = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    balance_stop_loss_base = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    mejor_horario = models.TimeField(null=True, blank=True)
    ultima_simulacion = models.DateTimeField(null=True, blank=True)
    pausado_desde = models.DateTimeField(null=True, blank=True)
    pausa_finaliza = models.DateTimeField(null=True, blank=True)
    en_operacion = models.BooleanField(default=False)
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración del bot"
        verbose_name_plural = "Configuraciones del bot"

    def __str__(self) -> str:
        return f"Configuración Bot #{self.pk}"

    @classmethod
    def obtener(cls) -> "ConfiguracionBot":
        instancia, _ = cls.objects.get_or_create(pk=1)
        instancia._asegurar_bases_y_objetivos()
        return instancia

    def calcular_monto_trade(self) -> Decimal:
        return (self.balance_actual * self.MONTO_TRADE_PORCENTAJE).quantize(
            Decimal("0.01")
        )

    def _calcular_meta_desde_base(self, base: Decimal) -> Decimal:
        return (base * self.META_PORCENTAJE).quantize(Decimal("0.01"))

    def _calcular_stop_loss_desde_base(self, base: Decimal) -> Decimal:
        return (base * self.STOP_LOSS_PORCENTAJE).quantize(Decimal("0.01"))

    def calcular_meta(self, base: Optional[Decimal] = None) -> Decimal:
        base_calculo = (
            base
            if base is not None
            else (self.balance_meta_base if self.balance_meta_base > 0 else self.balance_actual)
        )
        return self._calcular_meta_desde_base(base_calculo)

    def calcular_stop_loss(self, base: Optional[Decimal] = None) -> Decimal:
        base_calculo = (
            base
            if base is not None
            else (
                self.balance_stop_loss_base
                if self.balance_stop_loss_base > 0
                else self.balance_actual
            )
        )
        return self._calcular_stop_loss_desde_base(base_calculo)

    def _asegurar_bases_y_objetivos(self) -> None:
        cambios = False
        if self.balance_meta_base <= 0:
            self.balance_meta_base = self.balance_actual
            cambios = True
        if self.balance_stop_loss_base <= 0:
            self.balance_stop_loss_base = self.balance_actual
            cambios = True
        meta_calculada = self.calcular_meta(self.balance_meta_base)
        if self.meta_actual != meta_calculada:
            self.meta_actual = meta_calculada
            cambios = True
        stop_loss_calculado = self.calcular_stop_loss(self.balance_stop_loss_base)
        if self.stop_loss_actual != stop_loss_calculado:
            self.stop_loss_actual = stop_loss_calculado
            cambios = True
        perdida_calculada = self.balance_stop_loss_base - self.balance_actual
        if perdida_calculada < 0:
            perdida_calculada = Decimal("0.00")
        perdida_calculada = perdida_calculada.quantize(Decimal("0.01"))
        if self.perdida_acumulada != perdida_calculada:
            self.perdida_acumulada = perdida_calculada
            cambios = True
        if cambios:
            self.save(
                update_fields=[
                    "balance_meta_base",
                    "balance_stop_loss_base",
                    "meta_actual",
                    "stop_loss_actual",
                    "perdida_acumulada",
                    "ultima_actualizacion",
                ]
            )

    def registrar_ganancia(self, monto: Decimal) -> None:
        self.balance_actual = (self.balance_actual + monto).quantize(Decimal("0.01"))
        self.ganancia_acumulada = (
            self.ganancia_acumulada + monto
        ).quantize(Decimal("0.01"))
        self.perdida_acumulada = Decimal("0.00")

        if self.balance_actual > self.balance_stop_loss_base:
            self.balance_stop_loss_base = self.balance_actual

        if self.balance_meta_base <= 0:
            self.balance_meta_base = self.balance_actual

        meta_actual = self.calcular_meta(self.balance_meta_base)
        if self.balance_actual - self.balance_meta_base >= meta_actual:
            self.balance_meta_base = self.balance_actual
            meta_actual = self.calcular_meta(self.balance_meta_base)

        self.meta_actual = meta_actual
        self.stop_loss_actual = self.calcular_stop_loss(self.balance_stop_loss_base)
        self.save(
            update_fields=[
                "balance_actual",
                "ganancia_acumulada",
                "perdida_acumulada",
                "balance_meta_base",
                "balance_stop_loss_base",
                "meta_actual",
                "stop_loss_actual",
                "ultima_actualizacion",
            ]
        )

    def registrar_perdida(self, monto: Decimal) -> None:
        self.balance_actual = (self.balance_actual - monto).quantize(Decimal("0.01"))
        perdida = self.balance_stop_loss_base - self.balance_actual
        if perdida < 0:
            perdida = Decimal("0.00")
        self.perdida_acumulada = perdida.quantize(Decimal("0.01"))
        self.save(
            update_fields=["balance_actual", "perdida_acumulada", "ultima_actualizacion"]
        )

    def pausar(self, horas: int = 24) -> None:
        self.estado = self.Estado.PAUSADO
        self.pausado_desde = timezone.now()
        self.pausa_finaliza = self.pausado_desde + timezone.timedelta(hours=horas)
        self.en_operacion = False
        self.ultima_simulacion = None
        self.save(
            update_fields=[
                "estado",
                "pausado_desde",
                "pausa_finaliza",
                "ultima_simulacion",
                "en_operacion",
                "ultima_actualizacion",
            ]
        )

    def reanudar(self) -> None:
        self.estado = self.Estado.OPERANDO
        self.pausado_desde = None
        self.pausa_finaliza = None
        self.perdida_acumulada = Decimal("0.00")
        self.balance_meta_base = self.balance_actual
        self.balance_stop_loss_base = self.balance_actual
        self.meta_actual = self.calcular_meta(self.balance_meta_base)
        self.stop_loss_actual = self.calcular_stop_loss(self.balance_stop_loss_base)
        self.en_operacion = False
        self.mejor_horario = None
        self.ultima_simulacion = None
        self.save(
            update_fields=[
                "estado",
                "pausado_desde",
                "pausa_finaliza",
                "perdida_acumulada",
                "balance_meta_base",
                "balance_stop_loss_base",
                "meta_actual",
                "stop_loss_actual",
                "ultima_simulacion",
                "en_operacion",
                "mejor_horario",
                "ultima_actualizacion",
            ]
        )


class ActivoPermitido(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    descripcion = models.CharField(max_length=200, blank=True)
    habilitado = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    winrate_simulacion = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    hora_mejor_simulacion = models.TimeField(null=True, blank=True)
    ultima_simulacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Activo permitido"
        verbose_name_plural = "Activos permitidos"

    def __str__(self) -> str:
        return self.nombre
