"""
Modelos para el bot de trading inverso.
Base de datos separada del bot principal.
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone


class OperacionInversaQuerySet(models.QuerySet):
    """QuerySet personalizado para operaciones inversas."""
    
    def reales(self):
        """Solo operaciones reales (no simuladas)."""
        return self.filter(es_simulada=False)
    
    def simuladas(self):
        """Solo operaciones simuladas."""
        return self.filter(es_simulada=True)
    
    def ganadas(self):
        """Solo operaciones ganadas."""
        return self.filter(resultado=OperacionInversa.Resultado.GANADA)
    
    def perdidas(self):
        """Solo operaciones perdidas."""
        return self.filter(resultado=OperacionInversa.Resultado.PERDIDA)


class OperacionInversa(models.Model):
    """
    Operación del bot inverso.
    Siempre ejecuta la dirección opuesta al bot principal.
    """
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
    # Referencia a la operación del bot principal (si existe)
    operacion_principal_id = models.CharField(max_length=40, null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    objects = OperacionInversaQuerySet.as_manager()
    objetos = objects

    class Meta:
        ordering = ("-hora_inicio",)
        verbose_name = "Operación Inversa"
        verbose_name_plural = "Operaciones Inversas"
        indexes = [
            models.Index(fields=("activo", "hora_inicio")),
            models.Index(fields=("resultado", "hora_inicio")),
        ]

    def __str__(self) -> str:
        return f"[INVERSO] {self.activo} {self.direccion} #{self.numero_contrato}"


class ConfiguracionBotInverso(models.Model):
    """
    Configuración del bot inverso.
    Similar al bot principal pero con balance y estado separados.
    """
    MONTO_TRADE_PORCENTAJE = Decimal("0.005")
    META_PORCENTAJE = Decimal("0.01")
    STOP_LOSS_PORCENTAJE = Decimal("0.05")  # 5% para bot inverso

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
        verbose_name = "Configuración Bot Inverso"
        verbose_name_plural = "Configuraciones Bot Inverso"

    def __str__(self) -> str:
        return f"Configuración Bot Inverso #{self.pk}"

    @classmethod
    def obtener(cls) -> "ConfiguracionBotInverso":
        """Obtiene o crea la configuración única del bot inverso."""
        instancia, _ = cls.objects.get_or_create(pk=1)
        instancia._asegurar_bases_y_objetivos()
        return instancia

    def _asegurar_bases_y_objetivos(self) -> None:
        """Asegura que las bases y objetivos estén inicializados."""
        if self.balance_actual <= 0:
            return  # No inicializar si no hay balance
        
        if self.balance_meta_base <= 0:
            self.balance_meta_base = self.balance_actual
            self.save(update_fields=["balance_meta_base"])
        
        if self.balance_stop_loss_base <= 0:
            self.balance_stop_loss_base = self.balance_actual
            self.save(update_fields=["balance_stop_loss_base"])
        
        if self.stop_loss_actual <= 0:
            self.stop_loss_actual = self.calcular_stop_loss(self.balance_actual)
            self.save(update_fields=["stop_loss_actual"])

    def calcular_monto_trade(self) -> Decimal:
        """Calcula el monto del trade con mínimo de 0.40 USD."""
        monto_calculado = (self.balance_actual * self.MONTO_TRADE_PORCENTAJE).quantize(Decimal("0.01"))
        return max(monto_calculado, Decimal("0.40"))

    def calcular_stop_loss(self, balance: Decimal) -> Decimal:
        """Calcula el stop loss al 95% del balance (5% de pérdida máxima)."""
        return (balance * (Decimal("1") - self.STOP_LOSS_PORCENTAJE)).quantize(Decimal("0.01"))

    def calcular_meta(self, balance: Decimal) -> Decimal:
        """Calcula la meta al 101% del balance base."""
        return (self.balance_meta_base * (Decimal("1") + self.META_PORCENTAJE)).quantize(Decimal("0.01"))

    def registrar_ganancia(self, monto: Decimal) -> None:
        """Registra una ganancia y actualiza el stop loss (trailing)."""
        self.balance_actual += monto
        self.ganancia_acumulada += monto
        # Trailing stop loss: solo sube, nunca baja
        nuevo_stop_loss = self.calcular_stop_loss(self.balance_actual)
        if nuevo_stop_loss > self.stop_loss_actual:
            self.stop_loss_actual = nuevo_stop_loss
            self.balance_stop_loss_base = self.balance_actual
        self.save(
            update_fields=[
                "balance_actual",
                "ganancia_acumulada",
                "stop_loss_actual",
                "balance_stop_loss_base",
                "ultima_actualizacion",
            ]
        )

    def registrar_perdida(self, monto: Decimal) -> None:
        """Registra una pérdida. El stop loss NO se mueve (fijo)."""
        self.balance_actual -= monto
        self.perdida_acumulada += monto
        # Stop loss fijo: NO se actualiza en pérdidas
        self.save(
            update_fields=[
                "balance_actual",
                "perdida_acumulada",
                "ultima_actualizacion",
            ]
        )

    def pausar(self, horas: int = 1) -> None:
        """Pausa el bot por N horas. Por defecto 1 hora."""
        from datetime import timedelta
        self.estado = self.Estado.PAUSADO
        self.pausado_desde = timezone.now()
        self.pausa_finaliza = timezone.now() + timedelta(hours=horas)
        self.save(
            update_fields=["estado", "pausado_desde", "pausa_finaliza", "ultima_actualizacion"]
        )

    def reanudar(self) -> None:
        """Reanuda el bot y recalcula el stop loss."""
        self.estado = self.Estado.OPERANDO
        self.pausado_desde = None
        self.pausa_finaliza = None
        self.perdida_acumulada = Decimal("0.00")
        self.balance_meta_base = self.balance_actual
        self.balance_stop_loss_base = self.balance_actual
        self.meta_actual = Decimal("0.00")
        # Recalcular stop loss al 98% del balance actual
        self.stop_loss_actual = self.calcular_stop_loss(self.balance_actual)
        self.en_operacion = False
        self.ultima_simulacion = None
        self.save(
            update_fields=[
                "estado", "pausado_desde", "pausa_finaliza", "perdida_acumulada",
                "balance_meta_base", "balance_stop_loss_base", "meta_actual",
                "stop_loss_actual", "ultima_simulacion", "en_operacion",
                "mejor_horario", "ultima_actualizacion",
            ]
        )

