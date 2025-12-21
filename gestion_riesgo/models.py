from __future__ import annotations

from django.db import models


class Cuenta(models.Model):
    """
    ESTADO DE CUENTA PARA MONITOREO EN TIEMPO REAL.

    NOTA:
    - ESTA TABLA EXISTE PARA VISUALIZACIÓN Y GOBERNANZA (BALANCE/DRAWDOWN/BLOQUEO).
    - NO MEZCLA LÓGICA DE MERCADO NI ESTRATEGIA.
    """

    simbolo = models.CharField(max_length=32, default="R_100")
    # BALANCE REAL DESDE DERIV (API).
    balance_deriv = models.FloatField(null=True, blank=True)
    moneda_deriv = models.CharField(max_length=16, default="", blank=True)
    max_balance_deriv_historico = models.FloatField(null=True, blank=True)

    # EQUITY INTERNA (PAPER / GOBERNANZA) PARA VERIFICAR RIESGO SIN EJECUCIÓN REAL.
    capital_inicial = models.FloatField(default=100.0)
    capital_actual = models.FloatField(default=100.0)
    max_capital_historico = models.FloatField(default=100.0)
    bloqueado = models.BooleanField(default=False)

    ultimo_tick_epoch = models.BigIntegerField(default=0)
    ultimo_precio = models.FloatField(default=0.0)

    # ===== AUDITORÍA DE SEÑAL (ESTRATEGIA) =====
    # ESTO NO ES "LÓGICA": ES TELEMETRÍA PARA ENTENDER POR QUÉ EL BOT ENTRA O NO.
    senal_valor = models.FloatField(null=True, blank=True)
    senal_decision = models.CharField(max_length=16, blank=True, default="")
    senal_top_contribuciones = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        b = self.balance_deriv if self.balance_deriv is not None else self.capital_actual
        return f"Cuenta({self.simbolo}) balance={b:.2f} bloqueado={self.bloqueado}"


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


