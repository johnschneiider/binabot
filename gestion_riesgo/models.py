from __future__ import annotations

from django.db import models
from django.conf import settings


class Inversionista(models.Model):
    """
    Representa a un cliente/inversionista que deposita capital
    para que el bot opere en Deriv.
    """

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        PAUSADO = "PAUSADO", "Pausado"
        RETIRADO = "RETIRADO", "Retirado"

    class Genero(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"
        O = "O", "Otro"
        N = "N", "Prefiero no decir"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inversionista")
    nombre = models.CharField(max_length=100, default="")
    telefono = models.CharField(max_length=20, blank=True, default="")
    whatsapp = models.CharField(max_length=20, blank=True, default="")

    # KYC
    fecha_nacimiento = models.DateField(null=True, blank=True)
    nacionalidad = models.CharField(max_length=64, blank=True, default="")
    genero = models.CharField(max_length=1, choices=Genero.choices, default=Genero.N)
    documento_identidad = models.CharField(max_length=32, blank=True, default="")
    capital_objetivo = models.FloatField(default=0.0)
    como_se_entero = models.CharField(max_length=128, blank=True, default="")

    # Capital
    capital_inicial = models.FloatField(default=0.0)
    capital_actual = models.FloatField(default=0.0)
    ganancia_acumulada = models.FloatField(default=0.0)
    ganancia_mes = models.FloatField(default=0.0)

    # Config
    rendimiento_diario_pct = models.FloatField(default=0.5)
    fee_performance_pct = models.FloatField(default=25.0)

    # Estado
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.ACTIVO)
    observaciones = models.TextField(blank=True, default="")

    # Auditoria
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["estado"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Inversionista({self.user.username}) capital=${self.capital_actual:,.0f} estado={self.estado}"

    @property
    def rendimiento_pct(self) -> float:
        """Retorno % del inversionista desde que entró."""
        if self.capital_inicial <= 0:
            return 0.0
        return ((self.capital_actual - self.capital_inicial) / self.capital_inicial) * 100.0


class RendimientoDiario(models.Model):
    """
    Registro de rendimiento diario por inversionista.
    Se calcula cada día (o bajo demanda) para tracking de P&L.
    """

    inversionista = models.ForeignKey(Inversionista, on_delete=models.CASCADE, related_name="rendimientos_diarios")
    fecha = models.DateField()

    capital_inicio_dia = models.FloatField(default=0.0)
    capital_fin_dia = models.FloatField(default=0.0)
    ganancia_dia = models.FloatField(default=0.0)
    rendimiento_pct = models.FloatField(default=0.0)

    balance_deriv = models.FloatField(null=True, blank=True)
    trades_count = models.IntegerField(default=0)
    trades_wins = models.IntegerField(default=0)
    trades_losses = models.IntegerField(default=0)
    winrate = models.FloatField(default=0.0)

    observaciones = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["inversionista", "-fecha"]),
            models.Index(fields=["-fecha"]),
        ]
        unique_together = [["inversionista", "fecha"]]

    def __str__(self) -> str:
        return f"Rendimiento({self.inversionista.user.username} {self.fecha}) gain={self.ganancia_dia:+.2f}%"


class Liquidacion(models.Model):
    """
    Registro de liquidaciones (cobro del 25% sobre ganancias).
    """

    class Tipo(models.TextChoices):
        COBRO_FEE = "COBRO_FEE", "Cobro de fee"
        PAGO_INVERSIONISTA = "PAGO_INVERSIONISTA", "Pago a inversionista"
        DEPOSITO = "DEPOSITO", "Depósito"
        RETIRO = "RETIRO", "Retiro de capital"

    inversionista = models.ForeignKey(Inversionista, on_delete=models.CASCADE, related_name="liquidaciones")
    tipo = models.CharField(max_length=24, choices=Tipo.choices)

    ganancia_bruta = models.FloatField(default=0.0)
    fee_pct = models.FloatField(default=25.0)
    monto = models.FloatField(default=0.0)
    observaciones = models.TextField(blank=True, default="")

    fecha = models.DateField()
    confirmado = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["inversionista", "-fecha"]),
        ]
        ordering = ["-fecha"]

    def __str__(self) -> str:
        return f"Liquidacion({self.inversionista.user.username} {self.tipo} ${self.monto:,.0f})"


class BalanceInversionista(models.Model):
    """
    Snapshot diario del balance para graficar la curva de capital.
    """

    inversionista = models.ForeignKey(Inversionista, on_delete=models.CASCADE, related_name="balance_history")
    fecha = models.DateField()
    capital = models.FloatField()
    ganancia_acumulada = models.FloatField(default=0.0)
    ganancia_diaria = models.FloatField(default=0.0)
    rendimiento_dia_pct = models.FloatField(default=0.0)
    epoch = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["inversionista", "-fecha"]),
        ]
        unique_together = [["inversionista", "fecha"]]

    def __str__(self) -> str:
        return f"BalanceInversionista({self.inversionista.user.username} {self.fecha}) ${self.capital:,.0f}"


class Deposito(models.Model):
    """
    Registra depósitos de cada inversionista vía Bold.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        CANCELADO = "CANCELADO", "Cancelado"

    inversionista = models.ForeignKey(Inversionista, on_delete=models.CASCADE, related_name="depositos")
    monto = models.FloatField(default=0.0)
    referencia = models.CharField(max_length=64, blank=True, default="")
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.PENDIENTE)
    metodo = models.CharField(max_length=32, blank=True, default="BOLD")
    notas = models.TextField(blank=True, default="")
    fecha_creado = models.DateTimeField(auto_now_add=True)
    fecha_confirmado = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["inversionista", "-fecha_creado"]),
            models.Index(fields=["referencia"]),
            models.Index(fields=["estado"]),
        ]
        ordering = ["-fecha_creado"]

    def __str__(self) -> str:
        return f"Deposito({self.inversionista.user.username} ${self.monto:.0f} [{self.estado}])"


class Retiro(models.Model):
    """
    Solicitudes de retiro de cada inversionista.
    """

    class Estado(models.TextChoices):
        SOLICITADO = "SOLICITADO", "Solicitado"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        COMPLETADO = "COMPLETADO", "Completado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    inversionista = models.ForeignKey(Inversionista, on_delete=models.CASCADE, related_name="retiros")
    monto = models.FloatField(default=0.0)
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.SOLICITADO)
    destino = models.CharField(max_length=256, blank=True, default="")
    notas = models.TextField(blank=True, default="")
    notas_admin = models.TextField(blank=True, default="")
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_proceso = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["inversionista", "-fecha_solicitud"]),
            models.Index(fields=["estado"]),
        ]
        ordering = ["-fecha_solicitud"]

    def __str__(self) -> str:
        return f"Retiro({self.inversionista.user.username} ${self.monto:.0f} [{self.estado}])"


class RendimientoFondo(models.Model):
    """
    Rendimiento mensual real del fondo (todas las operaciones).
    Alimentado por el bot o manualmente para graficar la curva del fondo.
    """

    anno = models.IntegerField()
    mes = models.IntegerField()
    balance_inicio = models.FloatField(default=0.0)
    balance_fin = models.FloatField(default=0.0)
    ganancia = models.FloatField(default=0.0)
    rendimiento_pct = models.FloatField(default=0.0)
    trades_count = models.IntegerField(default=0)
    trades_wins = models.IntegerField(default=0)
    trades_losses = models.IntegerField(default=0)
    winrate = models.FloatField(default=0.0)
    observaciones = models.TextField(blank=True, default="")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-anno", "-mes"]),
        ]
        unique_together = [["anno", "mes"]]
        ordering = ["-anno", "-mes"]

    def __str__(self) -> str:
        return f"RendimientoFondo({self.anno}-{self.mes:02d}) {self.rendimiento_pct:+.2f}%"


class Cuenta(models.Model):
    """
    ESTADO DE CUENTA PARA MONITOREO EN TIEMPO REAL.

    NOTA:
    - ESTA TABLA EXISTE PARA VISUALIZACIÓN Y GOBERNANZA (BALANCE/DRAWDOWN/BLOQUEO).
    - NO MEZCLA LÓGICA DE MERCADO NI ESTRATEGIA.
    """

    # Default: R_10 para evitar “cuentas fantasma” R_100 en instalaciones nuevas.
    simbolo = models.CharField(max_length=32, default="R_10")
    # BALANCE REAL DESDE DERIV (API).
    balance_deriv = models.FloatField(null=True, blank=True)
    moneda_deriv = models.CharField(max_length=16, default="", blank=True)
    max_balance_deriv_historico = models.FloatField(null=True, blank=True)

    # EQUITY INTERNA (PAPER / GOBERNANZA) PARA VERIFICAR RIESGO SIN EJECUCIÓN REAL.
    capital_inicial = models.FloatField(default=100.0)
    capital_actual = models.FloatField(default=100.0)
    max_capital_historico = models.FloatField(default=100.0)
    bloqueado = models.BooleanField(default=False)
    # Motivo del bloqueo/estado de riesgo (solo telemetría/UI; la lógica se aplica en el bot).
    riesgo_motivo = models.CharField(max_length=64, blank=True, default="")

    # ===== CICLOS (MODO REAL) =====
    # Permite gobernanza por ciclos sobre el balance real (Deriv):
    # - Arranca ciclo con balance_inicio (baseline)
    # - Si llega a take profit => pausa 24h y reinicia ciclo al reanudar
    # - Si llega a stoploss => pausa 1h y reinicia ciclo al reanudar
    ciclo_balance_inicio = models.FloatField(null=True, blank=True)
    ciclo_inicio_epoch = models.BigIntegerField(null=True, blank=True)
    ciclo_pausa_hasta_epoch = models.BigIntegerField(null=True, blank=True)
    ciclo_ultimo_evento = models.CharField(max_length=64, blank=True, default="")

    ultimo_tick_epoch = models.BigIntegerField(default=0)
    ultimo_precio = models.FloatField(default=0.0)

    # ===== AUDITORÍA DE SEÑAL (ESTRATEGIA) =====
    # ESTO NO ES "LÓGICA": ES TELEMETRÍA PARA ENTENDER POR QUÉ EL BOT ENTRA O NO.
    senal_valor = models.FloatField(null=True, blank=True)
    senal_decision = models.CharField(max_length=16, blank=True, default="")
    senal_top_contribuciones = models.JSONField(null=True, blank=True)

    # ===== CONTROL MANUAL DEL BOT =====
    # Permite al usuario activar/desactivar el bot desde la UI
    bot_activo = models.BooleanField(default=True, help_text="Activar o desactivar el bot manualmente")

    # ===== COLECTOR DE TICKS (HISTÓRICO) =====
    # Permite dejar el bot en modo "recopilar ticks" por días sin operar necesariamente.
    # El bot sigue recibiendo ticks, pero solo los ARCHIVA si este flag está activo.
    ticks_colector_activo = models.BooleanField(default=True)
    ticks_colector_total = models.BigIntegerField(default=0)
    ticks_colector_ultimo_epoch = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        b = self.balance_deriv if self.balance_deriv is not None else self.capital_actual
        return f"Cuenta({self.simbolo}) balance={b:.2f} bloqueado={self.bloqueado} motivo={self.riesgo_motivo}"


class BalanceDerivSnapshot(models.Model):
    """
    HISTORIAL DE BALANCE REAL (DERIV) PARA GRAFICAR.

    Nota: se escribe con muestreo (ej. cada 60s) desde el bot para evitar crecimiento infinito.
    """

    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="balance_snapshots")
    balance = models.FloatField()
    moneda = models.CharField(max_length=16, blank=True, default="")
    epoch = models.BigIntegerField(null=True, blank=True)  # epoch UTC si se conoce

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["cuenta", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return f"BalanceSnapshot(cuenta={self.cuenta_id} balance={self.balance:.2f})"


class TickDerivSnapshot(models.Model):
    """
    ALMACENA LOS ÚLTIMOS TICKS PARA GRÁFICO EN TIEMPO REAL.
    
    Nota: Solo se mantienen los últimos 50 ticks por cuenta (limpieza automática).
    """
    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="tick_snapshots")
    precio = models.FloatField()
    epoch = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=["cuenta", "-epoch"]),
            models.Index(fields=["-epoch"]),
        ]
        ordering = ["-epoch"]
    
    def __str__(self) -> str:
        return f"TickSnapshot(cuenta={self.cuenta_id} precio={self.precio:.5f} epoch={self.epoch})"


class TickDerivHistorico(models.Model):
    """
    HISTÓRICO DE TICKS PARA INVESTIGACIÓN/BACKTEST.

    Nota:
    - A diferencia de `TickDerivSnapshot`, NO se limpia; puede crecer por días.
    - Se controla con `Cuenta.ticks_colector_activo` (pausar/reanudar desde dashboard).
    """

    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="ticks_historicos")
    precio = models.FloatField()
    epoch = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # Nombres explícitos para que coincidan con la migración 0013 en producción.
            models.Index(fields=["cuenta", "-epoch"], name="gestion_rie_cuenta__tch_idx"),
            models.Index(fields=["-epoch"], name="gestion_rie_epoch_tch_idx"),
        ]
        ordering = ["-epoch"]

    def __str__(self) -> str:
        return f"TickHistorico(cuenta={self.cuenta_id} precio={self.precio:.5f} epoch={self.epoch})"


class Operacion(models.Model):
    """
    REGISTRO DE OPERACIONES (PAPER) PARA VISUALIZACIÓN.
    """

    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "ABIERTA"
        CERRADA = "CERRADA", "CERRADA"

    class Direccion(models.TextChoices):
        LARGO = "LARGO", "LARGO"
        CORTO = "CORTO", "CORTO"

    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="operaciones")
    simbolo = models.CharField(max_length=32)

    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.ABIERTA)
    direccion = models.CharField(max_length=16, choices=Direccion.choices)

    precio_entrada = models.FloatField()
    precio_salida = models.FloatField(null=True, blank=True)

    tamanio = models.FloatField()
    stop_distancia = models.FloatField()

    pnl_realizado = models.FloatField(null=True, blank=True)
    motivo_cierre = models.CharField(max_length=64, blank=True, default="")

    opened_epoch = models.BigIntegerField(default=0)
    closed_epoch = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["simbolo", "-created_at"]),
            models.Index(fields=["estado", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Operacion({self.simbolo},{self.direccion},{self.estado})"


class VelaEURUSD(models.Model):
    """
    VELAS M5 PARA EURUSD (DEL DOCUMENTO ESTRATEGIA.TXT).
    
    Construcción: se build from ticks o desde API de candles de Deriv.
    """
    SIMBOLO = "EURUSD"
    
    timeframe = models.CharField(max_length=8, default="M5")  # M5, M1 para construcción
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.FloatField(default=0)
    epoch_inicio = models.BigIntegerField()  # epoch de apertura
    epoch_fin = models.BigIntegerField()     # epoch de cierre
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-epoch_inicio"]),
            models.Index(fields=["-epoch_fin"]),
        ]
        ordering = ["-epoch_inicio"]

    def __str__(self) -> str:
        return f"VelaEURUSD({self.timeframe} {self.epoch_inicio} O:{self.open:.5f} C:{self.close:.5f})"


class TickEURUSD(models.Model):
    """
    TICKS HISTÓRICOS DE EURUSD PARA CONSTRUCCIÓN DE VELAS Y BACKTESTING.
    """
    precio = models.FloatField()
    epoch = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-epoch"]),
        ]
        ordering = ["-epoch"]

    def __str__(self) -> str:
        return f"TickEURUSD({self.precio:.5f} @ {self.epoch})"


class OperacionBacktest(models.Model):
    """
    RESULTADOS DE BACKTESTING PARA EURUSD.
    """
    class Resultado(models.TextChoices):
        WIN = "WIN", "WIN"
        LOSS = "LOSS", "LOSS"

    vela_entrada = models.ForeignKey(VelaEURUSD, on_delete=models.CASCADE, related_name="backtest_ops")
    direccion = models.CharField(max_length=8)  # CALL / PUT
    precio_entrada = models.FloatField()
    precio_salida = models.FloatField()
    resultado = models.CharField(max_length=8, choices=Resultado.choices)
    pnl = models.FloatField()  # positivo=ganancia, negativo=pérdida
    senal_detalle = models.JSONField(default=dict)  # {trend, pullback_candles, confirm_type}
    epoch_entrada = models.BigIntegerField()
    epoch_salida = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-epoch_entrada"]

    def __str__(self) -> str:
        return f"Backtest({self.direccion} {self.resultado} pnl={self.pnl:.2f})"


class OperacionDeriv(models.Model):
    """
    HISTORIAL REAL DESDE DERIV (FUENTE DE VERDAD PARA EJECUCIÓN REAL).

    NOTA:
    - SE ALIMENTA DESDE `profit_table` Y/O `proposal_open_contract`.
    """

    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "ABIERTA"
        CERRADA = "CERRADA", "CERRADA"

    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="operaciones_deriv")
    simbolo = models.CharField(max_length=32)

    contract_id = models.BigIntegerField(unique=True)
    transaction_id = models.BigIntegerField(null=True, blank=True)

    # SOLO MOSTRAMOS EN DASHBOARD LAS OPERACIONES QUE ESTE BOT REALMENTE EJECUTÓ (ENTRADAS).
    creada_por_bot = models.BooleanField(default=False)

    contract_type = models.CharField(max_length=16, blank=True, default="")  # CALL/PUT, etc.
    longcode = models.TextField(blank=True, default="")
    shortcode = models.CharField(max_length=128, blank=True, default="")

    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.ABIERTA)
    moneda = models.CharField(max_length=16, blank=True, default="")

    buy_price = models.FloatField(null=True, blank=True)
    sell_price = models.FloatField(null=True, blank=True)
    payout = models.FloatField(null=True, blank=True)
    profit = models.FloatField(null=True, blank=True)

    # ===== SPOT (PRECIO DEL ÍNDICE) EN ENTRADA/SALIDA =====
    # Nota: buy_price/sell_price son stake/payout del contrato, NO el spot del mercado.
    entry_spot = models.FloatField(null=True, blank=True)
    exit_spot = models.FloatField(null=True, blank=True)

    # ===== TELEMETRÍA DE ENTRADA (PARA APRENDIZAJE ONLINE / AUDITORÍA) =====
    # Score s = w^T x en el instante de entrada (antes de enviar proposal/buy).
    senal_valor = models.FloatField(null=True, blank=True)
    # Umbral usado al momento de entrar (positivo; la venta usa el negativo).
    umbral_usado = models.FloatField(null=True, blank=True)
    # Snapshot (parcial) de pesos usados en la entrada (para trazabilidad).
    pesos_usados = models.JSONField(null=True, blank=True)
    # Top contribuciones en la entrada (para explicabilidad).
    senal_top_contribuciones = models.JSONField(null=True, blank=True)

    opened_epoch = models.BigIntegerField(null=True, blank=True)
    closed_epoch = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["simbolo", "-created_at"]),
            models.Index(fields=["estado", "-created_at"]),
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"OperacionDeriv({self.simbolo},contract_id={self.contract_id})"


class GrupoAcceso(models.Model):
    """
    Grupos de acceso por URL para gestionar permisos de usuarios.
    """

    nombre = models.CharField(max_length=80, unique=True)
    descripcion = models.TextField(blank=True, default="")
    urls_permitidas = models.TextField(
        blank=True,
        default="",
        help_text="Lista de rutas separadas por coma. Ej: /portal/,/portal/depositar/",
    )
    usuarios = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="grupos_acceso",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grupos_creados",
    )
    fecha_creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Grupo de Acceso"
        verbose_name_plural = "Grupos de Acceso"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class OperacionBinance(models.Model):
    """
    Operaciones ficticias del bot de Binance (paper trading).
    """
    
    class Direccion(models.TextChoices):
        CALL = "CALL", "Call (Compra)"
        PUT = "PUT", "Put (Venta)"
    
    class Confianza(models.TextChoices):
        ALTA = "alta", "Alta"
        MEDIA = "media", "Media"
        BAJA = "baja", "Baja"
    
    simbolo = models.CharField(max_length=20)
    direccion = models.CharField(max_length=10, choices=Direccion.choices)
    precio_entrada = models.DecimalField(max_digits=20, decimal_places=8)
    razon = models.CharField(max_length=100, blank=True, default="")
    confianza = models.CharField(max_length=10, choices=Confianza.choices, default="media")
    
    # Resultado
    es_win = models.BooleanField(default=False)
    profit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Estadísticas al momento de la operación
    win_rate_momento = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    profit_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    num_operacion = models.IntegerField(default=0)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Operacion Binance"
        verbose_name_plural = "Operaciones Binance"
        ordering = ["-created_at"]
    
    def __str__(self) -> str:
        resultado = "WIN" if self.es_win else "LOSS"
        return f"{self.simbolo} {self.direccion} {resultado} ({self.profit})"


class EstadisticasBinance(models.Model):
    """
    Estadísticas acumuladas por activo.
    """
    simbolo = models.CharField(max_length=20, unique=True)
    total_ops = models.IntegerField(default=0)
    wins = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    profit_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    win_streak = models.IntegerField(default=0)
    loss_streak = models.IntegerField(default=0)
    max_win_streak = models.IntegerField(default=0)
    max_loss_streak = models.IntegerField(default=0)
    balance_ficticio = models.DecimalField(max_digits=12, decimal_places=2, default=1000)
    ultima_operacion = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Estadistica Binance"
        verbose_name_plural = "Estadisticas Binance"
    
    def __str__(self) -> str:
        wr = (self.wins / self.total_ops * 100) if self.total_ops > 0 else 0
        return f"{self.simbolo}: WR {wr:.1f}% | Profit ${self.profit_total}"
    
    @property
    def win_rate(self) -> float:
        return (self.wins / self.total_ops * 100) if self.total_ops > 0 else 0


