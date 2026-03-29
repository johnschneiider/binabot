from django.db import models
from django.utils import timezone


class ConfiguracionTrading(models.Model):
    """
    Configuración general para operaciones de trading.
    """
    nombre = models.CharField(max_length=50, default="forex")
    
    ema_gap_min = models.FloatField(default=0.2, help_text="Gap mínimo entre EMA21 y EMA50 (%)")
    adx_min = models.FloatField(default=20.0, help_text="ADX mínimo para tendencia")
    rsi_min = models.FloatField(default=30.0, help_text="RSI mínimo")
    rsi_max = models.FloatField(default=70.0, help_text="RSI máximo")
    bb_min = models.FloatField(default=0.2, help_text="Posición mínima en Bollinger Bands")
    bb_max = models.FloatField(default=0.8, help_text="Posición máxima en Bollinger Bands")
    
    cooldown_ticks = models.IntegerField(default=150)
    stake = models.FloatField(default=1.0)
    duracion_segundos = models.IntegerField(default=60)
    payout = models.FloatField(default=0.95)
    
    activa = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Configuración Trading"
        verbose_name_plural = "Configuraciones Trading"
    
    def __str__(self):
        return f"Config {self.nombre} - EMA:{self.ema_gap_min}% ADX:{self.adx_min}"
    
    @classmethod
    def get_activa(cls):
        config = cls.objects.filter(activa=True).first()
        if not config:
            config = cls.objects.create(
                nombre="forex",
                ema_gap_min=0.2,
                adx_min=20.0,
                rsi_min=30.0,
                rsi_max=70.0,
                bb_min=0.2,
                bb_max=0.8,
                cooldown_ticks=150,
                stake=1.0,
                duracion_segundos=60,
                payout=0.95,
                activa=True
            )
        return config
    
    def reset_to_default(self):
        self.ema_gap_min = 0.2
        self.adx_min = 20.0
        self.rsi_min = 30.0
        self.rsi_max = 70.0
        self.bb_min = 0.2
        self.bb_max = 0.8
        self.cooldown_ticks = 150
        self.stake = 1.0
        self.duracion_segundos = 60
        self.payout = 0.95
        self.save()


class ActivoTrading(models.Model):
    simbolo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=50)
    pair_type = models.CharField(max_length=20, choices=[
        ('forex', 'Forex'),
        ('futures', 'Futures'),
        ('crypto', 'Crypto'),
    ], default='forex')
    activo = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Activo Trading"
        verbose_name_plural = "Activos Trading"
    
    def __str__(self):
        return f"{self.simbolo} - {self.nombre}"


class EstadisticasTrading(models.Model):
    simbolo = models.CharField(max_length=20, unique=True)
    total_ops = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    profit_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    balance_ficticio = models.DecimalField(max_digits=20, decimal_places=2, default=1000)
    win_streak = models.IntegerField(default=0)
    loss_streak = models.IntegerField(default=0)
    max_win_streak = models.IntegerField(default=0)
    max_loss_streak = models.IntegerField(default=0)
    ultima_operacion = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Estadísticas Trading"
        verbose_name_plural = "Estadísticas Trading"
    
    @property
    def win_rate(self):
        return (self.wins / self.total_ops * 100) if self.total_ops > 0 else 0
    
    def __str__(self):
        return f"{self.simbolo}: {self.total_ops} ops, WR {self.win_rate:.1f}%"


class OperacionTrading(models.Model):
    simbolo = models.CharField(max_length=20)
    direccion = models.CharField(max_length=10, choices=[('CALL', 'CALL'), ('PUT', 'PUT')])
    precio_entrada = models.DecimalField(max_digits=20, decimal_places=8)
    precio_salida = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    razon = models.CharField(max_length=100)
    confianza = models.CharField(max_length=20, choices=[('alta', 'Alta'), ('media', 'Media'), ('baja', 'Baja')], default='media')
    es_win = models.BooleanField(default=False)
    profit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    num_operacion = models.IntegerField(default=0)
    win_rate_momento = models.FloatField(default=0)
    profit_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Operación Trading"
        verbose_name_plural = "Operaciones Trading"
        ordering = ["-created_at"]
    
    def __str__(self):
        return f"{self.simbolo} {self.direccion} {'WIN' if self.es_win else 'LOSS'}"


class TickTrading(models.Model):
    simbolo = models.CharField(max_length=20, db_index=True)
    precio = models.DecimalField(max_digits=20, decimal_places=8)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = "Tick Trading"
        verbose_name_plural = "Ticks Trading"
        ordering = ["-timestamp"]
    
    def __str__(self):
        return f"{self.simbolo}: {self.precio}"


# ============================================================
#  FUNCIONES AUXILIARES
# ============================================================

def calcular_ema(prices, period):
    """Calcula EMA para una lista de precios."""
    if len(prices) < period:
        return None
    ema = prices[0]
    multiplier = 2 / (period + 1)
    for p in prices[1:]:
        ema = p * multiplier + ema * (1 - multiplier)
    return ema


def calcular_rsi(prices, period=14):
    """Calcula RSI para una lista de precios."""
    if len(prices) < period + 1:
        return 50
    gains = []
    losses = []
    for i in range(len(prices) - period, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calcular_bollinger(prices, period=20, std_dev=2):
    """Calcula Bollinger Bands."""
    if len(prices) < period:
        return None, None, None
    sma = sum(prices[-period:]) / period
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    return sma + std_dev * std, sma, sma - std_dev * std
