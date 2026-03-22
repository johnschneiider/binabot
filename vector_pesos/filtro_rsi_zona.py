from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Optional

from django.conf import settings


@dataclass(frozen=True)
class ResultadoFiltroRSI:
    decision: str  # "CONFIRMAR" | "INVALIDAR" | "NEUTRAL"
    razon: str
    rsi: float = 0.0
    momentum: float = 0.0
    ema_gap: float = 0.0
    confianza: str = "baja"  # "alta" | "media" | "baja"


@dataclass
class FiltroRSIZona:
    rsi_period: int = 14
    atr_period: int = 14
    momentum_period: int = 5
    
    oversold_threshold: float = 40.0
    overbought_threshold: float = 60.0
    momentum_threshold: float = 0.5
    ema_gap_threshold: float = 0.5
    
    enabled: bool = True
    
    _precios: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    _gains: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    _losses: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    _atrs: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    
    _rsi: float = 50.0
    _atr: float = 0.0
    _avg_gain: float = 0.0
    _avg_loss: float = 0.0
    
    _warmup: bool = True
    
    def __post_init__(self) -> None:
        self.enabled = getattr(settings, "RSI_ENABLED", True)
        self.rsi_period = int(getattr(settings, "RSI_PERIOD", 14) or 14)
        self.oversold_threshold = float(getattr(settings, "RSI_OVERSOLD", 40) or 40)
        self.overbought_threshold = float(getattr(settings, "RSI_OVERBOUGHT", 60) or 60)
        self.momentum_threshold = 0.3
        self.ema_gap_threshold = 0.3
    
    def actualizar(self, precio: float, ema_fast: float, ema_slow: float, tendencia: str) -> ResultadoFiltroRSI:
        """
        Actualiza indicadores y retorna decisión del filtro.
        
        Args:
            precio: Precio actual
            ema_fast: EMA rápida (20)
            ema_slow: EMA lenta (50)
            tendencia: "CALL" | "PUT" (dirección de la señal EMA)
        
        Returns:
            ResultadoFiltroRSI con decisión de confirmar/invalidar/neutral
        """
        if not self.enabled:
            return ResultadoFiltroRSI(decision="NEUTRAL", razon="filtro_deshabilitado")
        
        self._precios.append(precio)
        
        if len(self._precios) < 2:
            return ResultadoFiltroRSI(decision="NEUTRAL", razon="warmup")
        
        self._actualizar_rsi(precio)
        self._actualizar_atr(precio)
        
        if self._atr is None or self._atr == 0:
            return ResultadoFiltroRSI(decision="NEUTRAL", razon="atr_no_disponible")
        
        momentum = self._calcular_momentum()
        ema_gap = (ema_fast - ema_slow) / self._atr
        
        return self._evaluar_filtro(tendencia, momentum, ema_gap)
    
    def _actualizar_rsi(self, precio: float):
        """Actualiza RSI usando método estándar."""
        if len(self._precios) < 2:
            return
        
        cambio = precio - self._precios[-2]
        ganancia = max(cambio, 0)
        perdida = max(-cambio, 0)
        
        self._gains.append(ganancia)
        self._losses.append(perdida)
        
        if len(self._gains) < self.rsi_period:
            return
        
        if self._warmup:
            self._avg_gain = sum(self._gains) / len(self._gains)
            self._avg_loss = sum(self._losses) / len(self._losses)
            self._warmup = False
        else:
            alpha = 1.0 / self.rsi_period
            self._avg_gain = (1 - alpha) * self._avg_gain + alpha * ganancia
            self._avg_loss = (1 - alpha) * self._avg_loss + alpha * perdida
        
        if self._avg_loss == 0:
            self._rsi = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self._rsi = 100.0 - (100.0 / (1 + rs))
    
    def _actualizar_atr(self, precio: float):
        """Actualiza ATR usando rango verdadero."""
        if len(self._precios) < 2:
            return
        
        rango = abs(precio - self._precios[-2])
        self._atrs.append(rango)
        
        if len(self._atrs) < self.atr_period:
            return
        
        alpha = 1.0 / self.atr_period
        if self._atr == 0:
            self._atr = rango
        else:
            self._atr = alpha * rango + (1 - alpha) * self._atr
    
    def _calcular_momentum(self) -> float:
        """Calcula momentum normalizado por ATR."""
        if len(self._precios) < self.momentum_period + 1:
            return 0.0
        
        precio_actual = self._precios[-1]
        precio_pasado = self._precios[-(self.momentum_period + 1)]
        
        if self._atr is None or self._atr == 0:
            return 0.0
        
        return (precio_actual - precio_pasado) / self._atr
    
    def _evaluar_filtro(self, tendencia: str, momentum: float, ema_gap: float) -> ResultadoFiltroRSI:
        """
        Evalúa si la señal EMA debe ser confirmada, invalidada o ignorada.
        
        Lógica:
        - CALL: RSI < 40 + momentum > 0.5 + ema_gap > 0.5 → CONFIRMAR (alta confianza)
        - CALL: RSI > 60 → INVALIDAR
        - PUT: RSI > 60 + momentum < -0.5 + ema_gap < -0.5 → CONFIRMAR (alta confianza)
        - PUT: RSI < 40 → INVALIDAR
        - Otros casos → NEUTRAL
        """
        rsi = self._rsi
        
        if tendencia == "CALL":
            if rsi < self.oversold_threshold and momentum > self.momentum_threshold and ema_gap > self.ema_gap_threshold:
                return ResultadoFiltroRSI(
                    decision="CONFIRMAR",
                    razon=f"rsi_oversold_rsi{rsi:.1f}_mom{momentum:.2f}",
                    rsi=rsi,
                    momentum=momentum,
                    ema_gap=ema_gap,
                    confianza="alta"
                )
            elif rsi > self.overbought_threshold:
                return ResultadoFiltroRSI(
                    decision="INVALIDAR",
                    razon=f"rsi_overbought_invalida_rsi{rsi:.1f}",
                    rsi=rsi,
                    momentum=momentum,
                    ema_gap=ema_gap,
                    confianza="alta"
                )
            else:
                return ResultadoFiltroRSI(
                    decision="NEUTRAL",
                    razon=f"rsi_neutral_rsi{rsi:.1f}",
                    rsi=rsi,
                    momentum=momentum,
                    ema_gap=ema_gap,
                    confianza="media"
                )
        
        elif tendencia == "PUT":
            if rsi > self.overbought_threshold and momentum < -self.momentum_threshold and ema_gap < -self.ema_gap_threshold:
                return ResultadoFiltroRSI(
                    decision="CONFIRMAR",
                    razon=f"rsi_overbought_rsi{rsi:.1f}_mom{momentum:.2f}",
                    rsi=rsi,
                    momentum=momentum,
                    ema_gap=ema_gap,
                    confianza="alta"
                )
            elif rsi < self.oversold_threshold:
                return ResultadoFiltroRSI(
                    decision="INVALIDAR",
                    razon=f"rsi_oversold_invalida_rsi{rsi:.1f}",
                    rsi=rsi,
                    momentum=momentum,
                    ema_gap=ema_gap,
                    confianza="alta"
                )
            else:
                return ResultadoFiltroRSI(
                    decision="NEUTRAL",
                    razon=f"rsi_neutral_rsi{rsi:.1f}",
                    rsi=rsi,
                    momentum=momentum,
                    ema_gap=ema_gap,
                    confianza="media"
                )
        
        return ResultadoFiltroRSI(decision="NEUTRAL", razon="tendencia_desconocida")
    
    @property
    def rsi_actual(self) -> float:
        return self._rsi
