"""
Modelos para el motor de trading profesional.
Incluye cache de ticks, indicadores y rendimiento por activo.
"""
from decimal import Decimal
from typing import List

from django.db import models
from django.utils import timezone

from core.models import ActivoPermitido


class TickCache(models.Model):
    """
    Cache de los últimos ticks por activo para análisis rápido.
    Optimizado para consultas frecuentes en PostgreSQL.
    """
    activo = models.ForeignKey(
        ActivoPermitido,
        on_delete=models.CASCADE,
        related_name="tick_caches",
        db_index=True,
    )
    precio = models.DecimalField(max_digits=15, decimal_places=5)
    epoch = models.BigIntegerField(db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Tick en cache"
        verbose_name_plural = "Ticks en cache"
        ordering = ("-epoch",)
        indexes = [
            models.Index(fields=("-epoch", "activo")),
            models.Index(fields=("activo", "-timestamp")),
        ]

    def __str__(self) -> str:
        return f"{self.activo.nombre} @ {self.precio} ({self.epoch})"


class IndicadoresActivo(models.Model):
    """
    Indicadores técnicos calculados por activo.
    Se actualiza cada vez que se calculan nuevos indicadores.
    """
    activo = models.OneToOneField(
        ActivoPermitido,
        on_delete=models.CASCADE,
        related_name="indicadores",
        db_index=True,
    )
    
    # Indicadores de momentum
    momentum_simple = models.DecimalField(
        max_digits=15, decimal_places=5, default=Decimal("0.00")
    )
    momentum_pct = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal("0.00"),
        help_text="Cambio porcentual entre tick inicial y final"
    )
    
    # Volatilidad
    volatilidad = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal("0.00"),
        help_text="Desviación estándar de los últimos ticks"
    )
    
    # Tendencia
    tendencia_ema = models.DecimalField(
        max_digits=15, decimal_places=5, default=Decimal("0.00"),
        help_text="EMA(10) aplicada a los últimos ticks"
    )
    precio_actual = models.DecimalField(
        max_digits=15, decimal_places=5, default=Decimal("0.00")
    )
    
    # Rate of Change
    rate_of_change = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal("0.00"),
        help_text="Pendiente de regresión lineal"
    )
    
    # Fuerza de movimiento
    fuerza_movimiento = models.DecimalField(
        max_digits=15, decimal_places=5, default=Decimal("0.00"),
        help_text="|EMA - precio actual|"
    )
    
    # Consistencia
    consistencia = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Porcentaje de ticks consecutivos en la misma dirección"
    )
    
    # Score total
    score_total = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Score combinado 0-100"
    )
    
    # Dirección sugerida
    direccion_sugerida = models.CharField(
        max_length=4,
        choices=[("CALL", "CALL"), ("PUT", "PUT"), ("NONE", "Ninguna")],
        default="NONE",
    )
    
    # Metadata
    ticks_analizados = models.IntegerField(default=0)
    calculado_en = models.DateTimeField(auto_now=True, db_index=True)
    
    class Meta:
        verbose_name = "Indicadores de activo"
        verbose_name_plural = "Indicadores de activos"
        ordering = ("-score_total",)
        indexes = [
            models.Index(fields=("-score_total",)),
            models.Index(fields=("-calculado_en",)),
        ]

    def __str__(self) -> str:
        return f"{self.activo.nombre} - Score: {self.score_total}"


class RendimientoActivo(models.Model):
    """
    Rendimiento histórico y dinámico por activo.
    Incluye winrate, drawdown y resultados por franja horaria.
    """
    activo = models.ForeignKey(
        ActivoPermitido,
        on_delete=models.CASCADE,
        related_name="rendimientos",
        db_index=True,
    )
    
    # Winrate dinámico
    winrate_dinamico = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Winrate de las últimas N operaciones"
    )
    
    # Estadísticas
    total_operaciones = models.IntegerField(default=0)
    operaciones_ganadas = models.IntegerField(default=0)
    operaciones_perdidas = models.IntegerField(default=0)
    
    # Drawdown
    drawdown_maximo = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Drawdown máximo histórico"
    )
    drawdown_actual = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Drawdown actual"
    )
    
    # Beneficio/Pérdida
    beneficio_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    perdida_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    
    # Franja horaria
    hora = models.TimeField(db_index=True, help_text="Franja horaria (HH:MM)")
    
    # Metadata
    actualizado_en = models.DateTimeField(auto_now=True, db_index=True)
    periodo_desde = models.DateTimeField(
        null=True, blank=True,
        help_text="Inicio del período de análisis"
    )
    periodo_hasta = models.DateTimeField(
        null=True, blank=True,
        help_text="Fin del período de análisis"
    )
    
    class Meta:
        verbose_name = "Rendimiento de activo"
        verbose_name_plural = "Rendimientos de activos"
        ordering = ("-winrate_dinamico",)
        unique_together = [("activo", "hora")]
        indexes = [
            models.Index(fields=("-winrate_dinamico",)),
            models.Index(fields=("activo", "hora")),
            models.Index(fields=("-actualizado_en",)),
        ]

    def __str__(self) -> str:
        return f"{self.activo.nombre} @ {self.hora} - WR: {self.winrate_dinamico}%"


class CooldownActivo(models.Model):
    """
    Control de cooldown para activos que generan señales contradictorias.
    Evita operar el mismo activo demasiado frecuentemente.
    """
    activo = models.ForeignKey(
        ActivoPermitido,
        on_delete=models.CASCADE,
        related_name="cooldowns",
        db_index=True,
    )
    
    motivo = models.CharField(
        max_length=40,
        help_text="Razón del cooldown (señal contradictoria, micro-congestión, etc.)"
    )
    
    finaliza_en = models.DateTimeField(db_index=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Cooldown de activo"
        verbose_name_plural = "Cooldowns de activos"
        ordering = ("-finaliza_en",)
        indexes = [
            models.Index(fields=("activo", "finaliza_en")),
        ]

    def __str__(self) -> str:
        return f"{self.activo.nombre} - Cooldown hasta {self.finaliza_en}"

    def clean(self):
        """Valida que el motivo no exceda 40 caracteres."""
        super().clean()
        if self.motivo and len(self.motivo) > 40:
            self.motivo = self.motivo[:40]
    
    def save(self, *args, **kwargs):
        """Trunca el motivo antes de guardar."""
        if self.motivo and len(self.motivo) > 40:
            self.motivo = self.motivo[:40]
        if not self.motivo:
            self.motivo = "Cooldown activado"
        super().save(*args, **kwargs)
    
    @property
    def esta_activo(self) -> bool:
        """Verifica si el cooldown aún está activo."""
        return timezone.now() < self.finaliza_en
