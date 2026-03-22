from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from statistics import stdev
from typing import Optional


@dataclass(frozen=True)
class Tendencia:
    direccion: str  # "ALCISTA", "BAJISTA", "FLAT"
    pendiente: float  # slope de EMA (delta / delta_ticks)
    precio_vs_ema: float  # precio - ema


@dataclass(frozen=True)
class SenalEURUSD:
    decision: str  # "CALL", "PUT", "NO_OPERAR"
    razon: str  # descripción de por qué
    tendencia: Optional[Tendencia] = None
    vela_cruce: Optional[dict] = None  # datos de la vela que cruzó
    pullback_count: int = 0
    confirmacion: Optional[dict] = None  # {tipo, precio_rompido}


class IndicadorEMA35:
    """
    INDICADOR EMA 35 SEGÚN ESTRATEGIA.TXT
    
    Reglas:
    - EMA 35 periodos en timeframe M5
    - Tendencia Alcista: precio > EMA y pendiente positiva
    - Tendencia Bajista: precio < EMA y pendiente negativa
    - EMA plana -> no operar
    """
    
    def __init__(self, periodo: int = 35):
        self.periodo = periodo
        self._ema: Optional[float] = None
        self._ema_anterior: Optional[float] = None
        self._precios: deque[float] = deque(maxlen=periodo + 1)
        self._epochs: deque[int] = deque(maxlen=periodo + 1)
        self._ultimo_precio: Optional[float] = None
        self._ultimo_epoch: Optional[int] = None
    
    def actualizar(self, precio: float, epoch: int) -> float:
        """Actualiza con nuevo precio y retorna EMA actual."""
        self._ultimo_precio = precio
        self._ultimo_epoch = epoch
        
        self._precios.append(precio)
        self._epochs.append(epoch)
        
        alpha = 2.0 / (self.periodo + 1.0)
        
        if self._ema is None:
            self._ema = precio
        else:
            self._ema = alpha * precio + (1 - alpha) * self._ema
        
        self._ema_anterior = self._ema
        return self._ema
    
    @property
    def valor(self) -> Optional[float]:
        return self._ema
    
    @property
    def listo(self) -> bool:
        return self._ema is not None and len(self._precios) >= self.periodo
    
    def obtener_tendencia(self) -> Optional[Tendencia]:
        """Determina la tendencia según precio vs EMA."""
        if not self.listo or self._ultimo_precio is None or self._ema is None:
            return None
        
        precio_vs_ema = self._ultimo_precio - self._ema
        # Umbral muy pequeno para datos de alta frecuencia
        umbral = 0.00001  # 0.01 pip
        
        if abs(precio_vs_ema) < umbral:
            return Tendencia(direccion="FLAT", pendiente=0.0, precio_vs_ema=precio_vs_ema)
        
        if precio_vs_ema > 0:
            return Tendencia(direccion="ALCISTA", pendiente=precio_vs_ema, precio_vs_ema=precio_vs_ema)
        else:
            return Tendencia(direccion="BAJISTA", pendiente=precio_vs_ema, precio_vs_ema=precio_vs_ema)
    
    def _calcular_pendiente(self) -> float:
        """Calcula pendiente de EMA comparando con EMA de hace N ticks."""
        if len(self._precios) < 2:
            return 0.0
        
        # Comparar EMA actual con EMA de hace 10 ticks
        n = 10
        if len(self._precios) <= n:
            return 0.0
        
        # Obtener precio de hace n ticks
        precios_lista = list(self._precios)
        precio_hace_n = precios_lista[-(n+1)]
        
        # La pendiente es la diferencia entre el EMA actual y el precio de hace n ticks
        delta = self._ema - precio_hace_n
        return delta / n


class ConstructorVelasM5:
    """
    CONSTRUYE VELAS M5 DESDE TICKS.
    
    Cada vela = 5 minutos = 300 segundos.
    """
    
    def __init__(self):
        self._vela_actual: Optional[dict] = None
        self._ticks_en_vela: list[tuple[float, int]] = []
    
    def agregar_tick(self, precio: float, epoch: int) -> Optional[dict]:
        """
        Agrega tick y retorna vela completada si hay cambio de vela.
        Retorna dict de vela si se completó, None si aún no.
        """
        vela_duration = 300  # 5 minutos en segundos
        vela_epoch = (epoch // vela_duration) * vela_duration
        
        if self._vela_actual is None:
            self._vela_actual = {
                "epoch_inicio": vela_epoch,
                "open": precio,
                "high": precio,
                "low": precio,
                "close": precio,
            }
            self._ticks_en_vela = [(precio, epoch)]
            return None
        
        if vela_epoch != self._vela_actual["epoch_inicio"]:
            # Nueva vela - retornar la anterior completada
            vela_completada = self._construir_vela()
            
            # Iniciar nueva vela
            self._vela_actual = {
                "epoch_inicio": vela_epoch,
                "open": precio,
                "high": precio,
                "low": precio,
                "close": precio,
            }
            self._ticks_en_vela = [(precio, epoch)]
            return vela_completada
        
        # Actualizar vela actual
        self._vela_actual["high"] = max(self._vela_actual["high"], precio)
        self._vela_actual["low"] = min(self._vela_actual["low"], precio)
        self._vela_actual["close"] = precio
        self._ticks_en_vela.append((precio, epoch))
        return None
    
    def _construir_vela(self) -> dict:
        """Construye dict de vela desde los ticks actuales."""
        return {
            "epoch_inicio": self._vela_actual["epoch_inicio"],
            "epoch_fin": self._vela_actual["epoch_inicio"] + 300,
            "open": self._vela_actual["open"],
            "high": self._vela_actual["high"],
            "low": self._vela_actual["low"],
            "close": self._vela_actual["close"],
            "volume": len(self._ticks_en_vela),
        }
    
    @property
    def vela_actual(self) -> Optional[dict]:
        return self._vela_actual


def evaluar_senal_tendencia_simple(
    precios_recientes: list,
    precios_anteriores: list = None,
) -> SenalEURUSD:
    """
    ESTRATEGIA DE TENDENCIA CON CRUCE.
    
    Señales basadas en cruce de precio vs SMA:
    - CALL: precio Cruza de ABAJO hacia ARRIBA de SMA
    - PUT: precio Cruza de ARRIBA hacia ABAJO de SMA
    """
    if not precios_recientes or len(precios_recientes) < 6:
        return SenalEURUSD(decision="NO_OPERAR", razon="Sin suficientes datos")
    
    # Calcular SMA de 5 períodos
    sma5 = sum(precios_recientes[-5:]) / 5
    precio_actual = precios_recientes[-1]
    precio_anterior = precios_recientes[-2] if len(precios_recientes) >= 2 else precio_actual
    
    sma5_anterior = sum(precios_recientes[-6:-1]) / 5 if len(precios_recientes) >= 6 else sma5
    
    # Detectar cruce
    cruce_arriba = (precio_anterior < sma5_anterior and precio_actual > sma5)
    cruce_abajo = (precio_anterior > sma5_anterior and precio_actual < sma5)
    
    if cruce_arriba:
        return SenalEURUSD(
            decision="CALL",
            razon=f"CRUCE ALCISTA: {precio_anterior:.2f}->{precio_actual:.2f} cruza SMA5 {sma5_anterior:.2f}->{sma5:.2f}",
        )
    elif cruce_abajo:
        return SenalEURUSD(
            decision="PUT",
            razon=f"CRUCE BAJISTA: {precio_anterior:.2f}->{precio_actual:.2f} cruza SMA5 {sma5_anterior:.2f}->{sma5:.2f}",
        )
    
    return SenalEURUSD(
        decision="NO_OPERAR",
        razon=f"Sin cruce: precio={precio_actual:.2f} SMA5={sma5:.2f}"
    )


def evaluar_senal_reversion(
    precios_recientes: list,
    ema_valor: float,
) -> SenalEURUSD:
    """
    ESTRATEGIA DE REVERSIÓN A LA MEDIA.
    
    Señales:
    - CALL: precio está significativamente por debajo de EMA (sobreventa)
    - PUT: precio está significativamente por encima de EMA (sobrecompra)
    """
    if not precios_recientes or ema_valor is None:
        return SenalEURUSD(decision="NO_OPERAR", razon="Sin suficientes datos")
    
    precio_actual = precios_recientes[-1]
    precio_promedio = sum(precios_recientes) / len(precios_recientes)
    
    # Calcular desviación del promedio
    desviacion = precio_actual - precio_promedio
    
    # Usar desviación estándar como referencia
    if len(precios_recientes) >= 3:
        desv_std = stdev(precios_recientes) if len(precios_recientes) > 1 else 0.0001
    else:
        desv_std = 0.0001
    
    umbral = 1.5 * desv_std  # 1.5 desviaciones estándar
    
    if desviacion < -umbral:
        # Precio significativamente por debajo del promedio - sobreventa
        return SenalEURUSD(
            decision="CALL",
            razon=f"Sobreventa: precio={precio_actual:.5f} < promedio={precio_promedio:.5f}",
        )
    elif desviacion > umbral:
        # Precio significativamente por encima del promedio - sobrecompra
        return SenalEURUSD(
            decision="PUT",
            razon=f"Sobrecompra: precio={precio_actual:.5f} > promedio={precio_promedio:.5f}",
        )
    
    return SenalEURUSD(
        decision="NO_OPERAR",
        razon=f"Precio dentro del rango: desviacion={desviacion:.6f}"
    )


def evaluar_senal_momentum(
    precio_actual: float,
    precio_anterior: float,
    precio_hace_3: float,
) -> SenalEURUSD:
    """
    ESTRATEGIA BASADA EN MOMENTUM SIMPLE.
    
    Señales:
    - CALL: 3 velas alcistas consecutivas
    - PUT: 3 velas bajistas consecutivas
    """
    if precio_actual is None or precio_anterior is None or precio_hace_3 is None:
        return SenalEURUSD(decision="NO_OPERAR", razon="Sin suficientes datos")
    
    # Calcular dirección de las últimas 3 velas
    direccion_1 = 1 if precio_actual > precio_anterior else -1
    direccion_2 = 1 if precio_anterior > precio_hace_3 else -1
    
    # Si las últimas 2 direcciones son iguales, hay momentum
    if direccion_1 == direccion_2 == 1:
        return SenalEURUSD(
            decision="CALL",
            razon=f"Momentum alcista: {precio_hace_3:.5f} -> {precio_anterior:.5f} -> {precio_actual:.5f}",
        )
    elif direccion_1 == direccion_2 == -1:
        return SenalEURUSD(
            decision="PUT",
            razon=f"Momentum bajista: {precio_hace_3:.5f} -> {precio_anterior:.5f} -> {precio_actual:.5f}",
        )
    
    return SenalEURUSD(
        decision="NO_OPERAR",
        razon="Sin momentum claro"
    )


def evaluar_senal_simple(
    precio_actual: float,
    ema_valor: float,
    tendencia: Tendencia,
    precio_anterior: float,
    precio_hace_2: float,
) -> SenalEURUSD:
    """
    VERSIÓN SIMPLIFICADA para datos de alta frecuencia.
    
    Señales:
    - CALL: precio rompe arriba de EMA con momentum
    - PUT: precio rompe abajo de EMA con momentum
    """
    if tendencia is None or ema_valor is None:
        return SenalEURUSD(decision="NO_OPERAR", razon="Sin datos de tendencia")
    
    if tendencia.direccion == "FLAT":
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon="Mercado plano",
            tendencia=tendencia
        )
    
    # Detectar ruptura
    ruptura_alcista = (
        precio_anterior < ema_valor and 
        precio_actual > ema_valor and
        tendencia.direccion == "ALCISTA"
    )
    
    ruptura_bajista = (
        precio_anterior > ema_valor and 
        precio_actual < ema_valor and
        tendencia.direccion == "BAJISTA"
    )
    
    if ruptura_alcista:
        return SenalEURUSD(
            decision="CALL",
            razon=f"Ruptura ALCISTA: precio={precio_actual:.5f} > EMA={ema_valor:.5f}",
            tendencia=tendencia
        )
    elif ruptura_bajista:
        return SenalEURUSD(
            decision="PUT",
            razon=f"Ruptura BAJISTA: precio={precio_actual:.5f} < EMA={ema_valor:.5f}",
            tendencia=tendencia
        )
    
    return SenalEURUSD(
        decision="NO_OPERAR",
        razon="Sin ruptura clara",
        tendencia=tendencia
    )


def evaluar_senal_eurusd(
    velas: list[dict],
    ema35: IndicadorEMA35,
    *,
    pullback_min: int = 1,
    pullback_max: int = 3,
) -> SenalEURUSD:
    """
    EVALÚA SEÑAL SEGÚN ESTRATEGIA.TXT
    
    Pasos:
    1. Determinar tendencia (precio vs EMA + pendiente)
    2. Buscar cruce válido (vela cierra al otro lado de EMA)
    3. Esperar retroceso de 1-3 velas
    4. Confirmación: vela rompe máximo/mínimo previo
    """
    if len(velas) < 35 + 5:
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon="Sin suficientes velas para EMA 35"
        )
    
    # Obtener tendencia actual
    tendencia = ema35.obtener_tendencia()
    if tendencia is None:
        return SenalEURUSD(decision="NO_OPERAR", razon="EMA no lista")
    
    if tendencia.direccion == "FLAT":
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon="EMA plana - no operar",
            tendencia=tendencia
        )
    
    # Buscar cruce en las últimas velas
    # Un cruce ocurre cuando la vela anterior estaba en un lado y la actual cierra al otro
    vela_actual = velas[-1]
    vela_anterior = velas[-2]
    
    ema_val = ema35.valor
    if ema_val is None:
        return SenalEURUSD(decision="NO_OPERAR", razon="EMA sin valor")
    
    precio_cierre_actual = vela_actual["close"]
    precio_cierre_anterior = vela_anterior["close"]
    
    # Detectar cruce
    cruce_alcista = (
        precio_cierre_anterior < ema_val and 
        precio_cierre_actual > ema_val and
        tendencia.direccion == "ALCISTA"
    )
    cruce_bajista = (
        precio_cierre_anterior > ema_val and 
        precio_cierre_actual < ema_val and
        tendencia.direccion == "BAJISTA"
    )
    
    if not cruce_alcista and not cruce_bajista:
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon="Sin cruce válido",
            tendencia=tendencia
        )
    
    # Verificar que el cuerpo de la vela de cruce sea significativo
    cuerpo_vela = abs(precio_cierre_actual - vela_actual["open"])
    rango_vela = vela_actual["high"] - vela_actual["low"]
    
    if rango_vela > 0 and cuerpo_vela / rango_vela < 0.3:
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon="Cuerpo de vela de cruce no significativo",
            tendencia=tendencia,
            vela_cruce=vela_actual
        )
    
    # Buscar retroceso (pullback) de 1-3 velas en contra
    direccion_contra = -1 if tendencia.direccion == "ALCISTA" else 1
    pullback_count = 0
    pullback_encontrado = False
    
    for i in range(3, 0, -1):
        if len(velas) <= i:
            continue
        
        vela_pullback = velas[-i]
        
        if tendencia.direccion == "ALCISTA":
            # Pullback: vela bajista (cierre < open)
            es_contra = vela_pullback["close"] < vela_pullback["open"]
            # Verificar que toca o se acerca a la EMA
            toca_ema = vela_pullback["low"] <= ema_val * 1.001
        else:
            # Pullback: vela alcista
            es_contra = vela_pullback["close"] > vela_pullback["open"]
            toca_ema = vela_pullback["high"] >= ema_val * 0.999
        
        if es_contra and toca_ema:
            pullback_count = 4 - i  # 1, 2, o 3
            pullback_encontrado = True
            break
    
    if not pullback_encontrado:
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon="Sin retroceso válido (no toca EMA)",
            tendencia=tendencia,
            vela_cruce=vela_actual
        )
    
    if pullback_count < pullback_min or pullback_count > pullback_max:
        return SenalEURUSD(
            decision="NO_OPERAR",
            razon=f"Retroceso fuera de rango ({pullback_count} velas)",
            tendencia=tendencia,
            vela_cruce=vela_actual,
            pullback_count=pullback_count
        )
    
    # Confirmación: vela rompe máximo/mínimo previo
    # Buscar la última vela en dirección de la tendencia (no pullback)
    indice_buscar = -pullback_count - 1
    if len(velas) > abs(indice_buscar):
        vela_pre_pullback = velas[indice_buscar]
        
        if tendencia.direccion == "ALCISTA":
            # CALL: vela alcista rompe máximo previo
            maxima_previo = max(v["high"] for v in velas[indice_buscar:indice_buscar+3] if v != vela_actual)
            confirmacion_rota = precio_cierre_actual > maxima_previo
            tipo_confirmacion = "rompe_maximo"
        else:
            # PUT: vela bajista rompe mínimo previo
            minima_previo = min(v["low"] for v in velas[indice_buscar:indice_buscar+3] if v != vela_actual)
            confirmacion_rota = precio_cierre_actual < minima_previo
            tipo_confirmacion = "rompe_minimo"
        
        if not confirmacion_rota:
            return SenalEURUSD(
                decision="NO_OPERAR",
                razon=f"Sin confirmación ({tipo_confirmacion})",
                tendencia=tendencia,
                vela_cruce=vela_actual,
                pullback_count=pullback_count
            )
        
        # SEÑAL VÁLIDA
        decision = "CALL" if tendencia.direccion == "ALCISTA" else "PUT"
        
        return SenalEURUSD(
            decision=decision,
            razon=f"Señal válida: {decision} por {tendencia.direccion} con pullback de {pullback_count} velas",
            tendencia=tendencia,
            vela_cruce=vela_actual,
            pullback_count=pullback_count,
            confirmacion={"tipo": tipo_confirmacion, "vela": vela_actual}
        )
    
    return SenalEURUSD(
        decision="NO_OPERAR",
        razon="No se encontró vela previa para confirmación",
        tendencia=tendencia,
        vela_cruce=vela_actual,
        pullback_count=pullback_count
    )
