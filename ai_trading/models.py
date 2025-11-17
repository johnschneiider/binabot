from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


class EstrategiaGenetica(models.Model):
    """
    Representa una estrategia de trading con parámetros genéticos.
    Cada estrategia es un "individuo" en el algoritmo genético.
    """
    nombre = models.CharField(max_length=200, unique=True)
    descripcion = models.TextField(blank=True)
    
    # Parámetros genéticos (genes)
    # Estos son los parámetros que el algoritmo genético optimizará
    umbral_variacion_min = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.10"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("10.00"))],
        help_text="Variación mínima de precio para considerar una señal (porcentaje)"
    )
    umbral_confianza_min = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("99.99"))],
        help_text="Confianza mínima requerida para operar"
    )
    ventana_ticks = models.PositiveIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Cantidad de ticks a analizar para generar señal"
    )
    peso_winrate_simulacion = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("1.00"))],
        help_text="Peso del winrate de simulación en la decisión (0-1)"
    )
    peso_confianza_horario = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.30"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("1.00"))],
        help_text="Peso de la confianza horaria en la decisión (0-1)"
    )
    umbral_riesgo_max = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("2.00"),
        validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("10.00"))],
        help_text="Riesgo máximo permitido (multiplicador del stop loss)"
    )
    
    # Métricas de rendimiento (fitness)
    fitness = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0.0000"),
        help_text="Valor de fitness calculado por el algoritmo genético"
    )
    operaciones_evaluadas = models.PositiveIntegerField(default=0)
    ganadas = models.PositiveIntegerField(default=0)
    perdidas = models.PositiveIntegerField(default=0)
    winrate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    beneficio_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    sharpe_ratio = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal("0.0000"),
        help_text="Ratio de Sharpe (medida de riesgo/retorno)"
    )
    
    # Estado y control
    activa = models.BooleanField(default=True)
    generacion = models.PositiveIntegerField(default=0)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    ultima_evaluacion = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Estrategia Genética"
        verbose_name_plural = "Estrategias Genéticas"
        ordering = ["-fitness", "-generacion"]
        indexes = [
            models.Index(fields=["-fitness"]),
            models.Index(fields=["generacion"]),
            models.Index(fields=["activa"]),
        ]
    
    def __str__(self):
        return f"{self.nombre} (Gen {self.generacion}, Fitness: {self.fitness:.4f})"
    
    def calcular_winrate(self):
        """Calcula el winrate basado en operaciones evaluadas"""
        if self.operaciones_evaluadas == 0:
            return Decimal("0.00")
        return (Decimal(self.ganadas) / Decimal(self.operaciones_evaluadas) * Decimal("100")).quantize(
            Decimal("0.01")
        )
    
    def actualizar_metricas(self):
        """Actualiza las métricas de rendimiento"""
        self.winrate = self.calcular_winrate()
        self.save(update_fields=["winrate", "actualizada"])


class PoblacionGenetica(models.Model):
    """
    Representa una generación completa de estrategias genéticas.
    """
    nombre = models.CharField(max_length=200)
    generacion = models.PositiveIntegerField(default=0)
    tamano_poblacion = models.PositiveIntegerField(default=50)
    estrategias = models.ManyToManyField(EstrategiaGenetica, related_name="poblaciones")
    
    # Parámetros del algoritmo genético
    tasa_mutacion = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.10"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("1.00"))]
    )
    tasa_crossover = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.80"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("1.00"))]
    )
    elite_size = models.PositiveIntegerField(
        default=5,
        help_text="Cantidad de mejores estrategias que pasan directamente a la siguiente generación"
    )
    
    # Métricas de la población
    fitness_promedio = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0.0000")
    )
    fitness_mejor = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0.0000")
    )
    fitness_peor = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0.0000")
    )
    
    # Control
    completada = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Población Genética"
        verbose_name_plural = "Poblaciones Genéticas"
        ordering = ["-generacion", "-fitness_promedio"]
        unique_together = [["nombre", "generacion"]]
    
    def __str__(self):
        return f"{self.nombre} - Generación {self.generacion}"


class EvaluacionEstrategia(models.Model):
    """
    Registra una evaluación específica de una estrategia sobre datos históricos.
    """
    estrategia = models.ForeignKey(
        EstrategiaGenetica,
        on_delete=models.CASCADE,
        related_name="evaluaciones"
    )
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    activos_evaluados = models.JSONField(
        default=list,
        help_text="Lista de activos usados en la evaluación"
    )
    
    # Resultados de la evaluación
    operaciones_totales = models.PositiveIntegerField(default=0)
    operaciones_ganadas = models.PositiveIntegerField(default=0)
    operaciones_perdidas = models.PositiveIntegerField(default=0)
    winrate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    beneficio_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    max_drawdown = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Máxima pérdida consecutiva"
    )
    sharpe_ratio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0.0000"))
    
    # Detalles adicionales
    detalles = models.JSONField(
        default=dict,
        help_text="Información adicional de la evaluación"
    )
    
    creada = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Evaluación de Estrategia"
        verbose_name_plural = "Evaluaciones de Estrategias"
        ordering = ["-creada"]
        indexes = [
            models.Index(fields=["-creada"]),
            models.Index(fields=["estrategia", "-creada"]),
        ]
    
    def __str__(self):
        return f"Evaluación {self.estrategia.nombre} - {self.creada.strftime('%Y-%m-%d %H:%M')}"


class TradeIA(models.Model):
    """
    Registra un trade ejecutado por una estrategia de IA.
    Completamente independiente del bot principal.
    """
    class Resultado(models.TextChoices):
        PENDIENTE = "pending", "Pendiente"
        GANADO = "win", "Ganado"
        PERDIDO = "loss", "Perdido"
    
    estrategia = models.ForeignKey(
        EstrategiaGenetica,
        on_delete=models.CASCADE,
        related_name="trades"
    )
    activo = models.CharField(max_length=80)
    direccion = models.CharField(max_length=4)  # CALL o PUT
    precio_entrada = models.DecimalField(max_digits=12, decimal_places=5)
    precio_salida = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    monto_invertido = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    resultado = models.CharField(max_length=10, choices=Resultado.choices, default=Resultado.PENDIENTE)
    beneficio = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    reward = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0.0000"),
        help_text="Recompensa o castigo para el algoritmo genético"
    )
    hora_inicio = models.DateTimeField(auto_now_add=True)
    hora_fin = models.DateTimeField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Trade de IA"
        verbose_name_plural = "Trades de IA"
        ordering = ["-hora_inicio"]
        indexes = [
            models.Index(fields=["estrategia", "-hora_inicio"]),
            models.Index(fields=["resultado", "-hora_inicio"]),
        ]
    
    def __str__(self):
        return f"{self.estrategia.nombre} - {self.activo} {self.direccion} - {self.resultado}"


class EntrenamientoIA(models.Model):
    """
    Registra sesiones de entrenamiento de la IA.
    """
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_CURSO = "en_curso", "En Curso"
        COMPLETADO = "completado", "Completado"
        ERROR = "error", "Error"
        CANCELADO = "cancelado", "Cancelado"
    
    nombre = models.CharField(max_length=200)
    tipo = models.CharField(
        max_length=50,
        choices=[
            ("genetico", "Algoritmo Genético"),
            ("rl", "Reinforcement Learning"),
            ("hibrido", "Híbrido (Genético + RL)"),
        ],
        default="genetico"
    )
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    
    # Parámetros de entrenamiento
    generaciones = models.PositiveIntegerField(default=50)
    tamano_poblacion = models.PositiveIntegerField(default=50)
    datos_desde = models.DateTimeField(null=True, blank=True)
    datos_hasta = models.DateTimeField(null=True, blank=True)
    activos_incluidos = models.JSONField(
        default=list,
        help_text="Lista de activos a incluir en el entrenamiento (vacío = todos)"
    )
    
    # Resultados
    mejor_estrategia = models.ForeignKey(
        EstrategiaGenetica,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entrenamientos_como_mejor"
    )
    fitness_final = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    progreso = models.JSONField(
        default=dict,
        help_text="Historial de progreso del entrenamiento"
    )
    
    # Control
    iniciada = models.DateTimeField(null=True, blank=True)
    finalizada = models.DateTimeField(null=True, blank=True)
    duracion_segundos = models.PositiveIntegerField(null=True, blank=True)
    error_mensaje = models.TextField(blank=True)
    
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Entrenamiento de IA"
        verbose_name_plural = "Entrenamientos de IA"
        ordering = ["-creada"]
    
    def __str__(self):
        return f"{self.nombre} - {self.get_estado_display()} ({self.tipo})"

